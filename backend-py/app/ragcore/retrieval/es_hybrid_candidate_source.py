"""ES 原生 BM25/kNN 双路候选召回(遗留兼容入口)。禁止构造无 org/kb filter 的查询。

对应 Java 版 `ragcore/retrieval/ElasticsearchHybridCandidateSource.java`。
新生产代码应使用 `LexicalCandidateSource` + `VectorCandidateSource` + `ChunkHydrator`
三端口独立组装;本类仅供评测脚本与存量测试复用。
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from elasticsearch import AsyncElasticsearch

from app.core.config import Settings, settings as default_settings
from app.ragcore.index.exceptions import ElasticsearchIndexException
from app.ragcore.index.search_request import SearchRequest
from app.ragcore.model import RetrievedChunk
from app.ragcore.retrieval.es_chunk_document_mapper import SOURCE_FIELDS, to_chunk
from app.ragcore.retrieval.hybrid_candidate_source import HybridCandidateSource
from app.ragcore.retrieval.vector_search_request import VectorSearchRequest

logger = logging.getLogger(__name__)


class ElasticsearchHybridCandidateSource(HybridCandidateSource):
    def __init__(
        self,
        es_client: AsyncElasticsearch,
        cfg: Settings | None = None,
        index_name: str | None = None,
        vector_dimensions: int | None = None,
    ) -> None:
        self._es = es_client
        cfg = cfg or default_settings
        self._index_name = index_name or cfg.rag_es_index_name
        self._vector_dimensions = vector_dimensions or cfg.rag_es_vector_dimensions

    async def search_bm25(self, request: SearchRequest) -> list[RetrievedChunk]:
        self._require_boundary(request.organization_id, request.knowledge_base_id)
        if not request.query or not request.query.strip():
            return []
        body: dict[str, Any] = {
            "size": request.top_k,
            "_source": list(SOURCE_FIELDS),
            "query": {
                "bool": {
                    "filter": self._tenant_filters(
                        request.organization_id,
                        request.knowledge_base_id,
                        request.document_ids,
                    ),
                    "should": [
                        {"term": {"symbol_names": {"value": request.query, "boost": 8}}},
                        {"term": {"config_keys": {"value": request.query, "boost": 7}}},
                        {"term": {"error_codes": {"value": request.query, "boost": 7}}},
                        {"match": {"content_search": {"query": request.query, "boost": 1}}},
                    ],
                    "minimum_should_match": 1,
                }
            },
        }
        return await self._execute(body, bm25=True)

    async def search_knn(self, request: VectorSearchRequest) -> list[RetrievedChunk]:
        self._require_boundary(request.organization_id, request.knowledge_base_id)
        if len(request.query_vector) != self._vector_dimensions:
            raise ValueError(f"查询向量维度必须为 {self._vector_dimensions}")
        body: dict[str, Any] = {
            "size": request.top_k,
            "_source": list(SOURCE_FIELDS),
            "knn": {
                "field": "content_vector",
                "query_vector": list(request.query_vector),
                "k": request.top_k,
                "num_candidates": max(100, request.top_k * 3),
                "filter": self._tenant_filters(
                    request.organization_id,
                    request.knowledge_base_id,
                    request.document_ids,
                ),
            },
        }
        return await self._execute(body, bm25=False)

    # ---- 内部实现 --------------------------------------------------------

    async def _execute(self, body: dict[str, Any], bm25: bool) -> list[RetrievedChunk]:
        try:
            response = await self._es.search(index=self._index_name, body=body)
        except Exception as ex:  # noqa: BLE001
            raise ElasticsearchIndexException("ES 候选召回失败") from ex
        hits = self._extract_hits(response)
        if hits is None:
            raise ElasticsearchIndexException("ES 搜索响应缺少 hits.hits")

        result: list[RetrievedChunk] = []
        for rank, hit in enumerate(hits, start=1):
            source = self._hit_source(hit)
            try:
                chunk = to_chunk(source)
            except ElasticsearchIndexException as ex:
                logger.warning("ES 候选反序列化失败,跳过: %s", ex)
                continue
            score = self._hit_score(hit)
            if bm25:
                result.append(
                    RetrievedChunk(
                        chunk=chunk,
                        bm25_rank=rank,
                        vector_rank=None,
                        rrf_score=None,
                        rerank_score=None,
                        final_score=score,
                    )
                )
            else:
                result.append(
                    RetrievedChunk(
                        chunk=chunk,
                        bm25_rank=None,
                        vector_rank=rank,
                        rrf_score=None,
                        rerank_score=None,
                        final_score=score,
                    )
                )
        return result

    @staticmethod
    def _tenant_filters(
        organization_id: UUID, knowledge_base_id: UUID, document_ids: tuple[UUID, ...]
    ) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = [
            {"term": {"org_id": str(organization_id)}},
            {"term": {"kb_id": str(knowledge_base_id)}},
            {"term": {"retrieval_ready": True}},
        ]
        if document_ids:
            filters.append(
                {"terms": {"document_id": [str(d) for d in document_ids]}}
            )
        return filters

    @staticmethod
    def _require_boundary(organization_id: UUID | None, knowledge_base_id: UUID | None) -> None:
        if organization_id is None or knowledge_base_id is None:
            raise ValueError("检索请求必须携带服务端组织与知识库边界")

    @staticmethod
    def _extract_hits(response: Any) -> list[Any] | None:
        if response is None:
            return None
        if isinstance(response, dict):
            payload = response.get("hits", {})
        elif hasattr(response, "body") and isinstance(response.body, dict):
            payload = response.body.get("hits", {})
        else:
            return None
        if not isinstance(payload, dict):
            return None
        hits_obj = payload.get("hits")
        if not isinstance(hits_obj, list):
            return None
        return hits_obj

    @staticmethod
    def _hit_source(hit: Any) -> Any:
        if isinstance(hit, dict):
            return hit.get("_source")
        if hasattr(hit, "field"):
            try:
                return hit.field("_source")
            except Exception:  # noqa: BLE001
                return None
        return None

    @staticmethod
    def _hit_score(hit: Any) -> float | None:
        if isinstance(hit, dict):
            score = hit.get("_score")
            return float(score) if isinstance(score, (int, float)) else None
        if hasattr(hit, "field"):
            try:
                score = hit.field("_score")
            except Exception:  # noqa: BLE001
                return None
            return float(score) if isinstance(score, (int, float)) else None
        return None
