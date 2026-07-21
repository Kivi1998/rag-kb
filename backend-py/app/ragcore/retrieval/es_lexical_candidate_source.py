"""ES 原生 BM25 候选召回,保留代码符号、配置键和 boost 权重的精确移植。

对应 Java 版 `ragcore/retrieval/ElasticsearchLexicalCandidateSource.java`。
所有查询的 bool.filter 必含 organization_id / knowledge_base_id / retrieval_ready=true;
document_ids 非空时叠加 document_id 范围过滤——这是第二道租户过滤,第一道由调用方
注入到 SearchRequest 中。
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
from app.ragcore.retrieval.lexical_candidate_source import LexicalCandidateSource

logger = logging.getLogger(__name__)


class ElasticsearchLexicalCandidateSource(LexicalCandidateSource):
    def __init__(
        self,
        es_client: AsyncElasticsearch,
        cfg: Settings | None = None,
        index_name: str | None = None,
    ) -> None:
        self._es = es_client
        cfg = cfg or default_settings
        self._index_name = index_name or cfg.rag_es_index_name

    async def search(self, request: SearchRequest) -> list[RetrievedChunk]:
        self._require_boundary(request.organization_id, request.knowledge_base_id)
        if not request.query or not request.query.strip():
            return []

        body: dict[str, Any] = {
            "size": request.top_k,
            "_source": list(SOURCE_FIELDS),
            "query": {
                "bool": {
                    "filter": self._tenant_filters(
                        request.organization_id, request.knowledge_base_id, request.document_ids
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
        try:
            response = await self._es.search(index=self._index_name, body=body)
        except Exception as ex:  # noqa: BLE001
            raise ElasticsearchIndexException("ES BM25 召回失败") from ex

        hits = self._extract_hits(response)
        if hits is None:
            raise ElasticsearchIndexException("ES 搜索响应缺少 hits.hits")

        result: list[RetrievedChunk] = []
        for rank, hit in enumerate(hits, start=1):
            source = self._hit_source(hit)
            try:
                chunk = to_chunk(source)
            except ElasticsearchIndexException as ex:
                logger.warning("ES BM25 候选反序列化失败,跳过: %s", ex)
                continue
            score = self._hit_score(hit)
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
        return result

    # ---- 内部辅助 --------------------------------------------------------

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
            raise ValueError("BM25 请求必须携带组织与知识库边界")

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
                return float(score) if isinstance(score, (int, float)) else None
            except Exception:  # noqa: BLE001
                return None
        return None
