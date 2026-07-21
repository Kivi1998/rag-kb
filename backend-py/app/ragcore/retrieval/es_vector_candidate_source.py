"""ES kNN 基线与回滚候选源;只返回 Chunk ID、排名和分数。

对应 Java 版 `ragcore/retrieval/ElasticsearchVectorCandidateSource.java`。
knn.filter 在 ES 侧强制 org_id/kb_id/retrieval_ready=true;document_ids 非空时
叠加 document_id 范围过滤。
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from elasticsearch import AsyncElasticsearch

from app.core.config import Settings, settings as default_settings
from app.ragcore.index.exceptions import ElasticsearchIndexException
from app.ragcore.retrieval.vector_candidate_source import VectorCandidateSource
from app.ragcore.retrieval.vector_hit import VectorHit
from app.ragcore.retrieval.vector_search_request import VectorSearchRequest

logger = logging.getLogger(__name__)


class ElasticsearchVectorCandidateSource(VectorCandidateSource):
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

    async def search(self, request: VectorSearchRequest) -> list[VectorHit]:
        if len(request.query_vector) != self._vector_dimensions:
            raise ValueError(f"查询向量维度必须为 {self._vector_dimensions}")
        self._require_boundary(request.organization_id, request.knowledge_base_id)

        body: dict[str, Any] = {
            "size": request.top_k,
            "_source": ["chunk_id"],
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
        try:
            response = await self._es.search(index=self._index_name, body=body)
        except Exception as ex:  # noqa: BLE001
            raise ElasticsearchIndexException("ES kNN 召回失败") from ex

        hits = self._extract_hits(response)
        if hits is None:
            raise ElasticsearchIndexException("ES kNN 响应缺少 hits.hits")

        result: list[VectorHit] = []
        for rank, hit in enumerate(hits, start=1):
            chunk_id = self._hit_chunk_id(hit)
            if not chunk_id:
                logger.warning("ES kNN 命中缺少 chunk_id,跳过: rank=%d", rank)
                continue
            score = self._hit_score(hit)
            result.append(VectorHit(chunk_id=chunk_id, rank=rank, score=score))
        return result

    # ---- 内部辅助 --------------------------------------------------------

    @staticmethod
    def _tenant_filters(
        organization_id: UUID, knowledge_base_id: UUID, document_ids: tuple[UUID, ...]
    ) -> list[dict[str, Any]]:
        if organization_id is None or knowledge_base_id is None:
            raise ValueError("向量请求必须携带组织与知识库边界")
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
            raise ValueError("向量请求必须携带组织与知识库边界")

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
    def _hit_chunk_id(hit: Any) -> str | None:
        if isinstance(hit, dict):
            source = hit.get("_source")
            if isinstance(source, dict):
                value = source.get("chunk_id")
                return str(value) if value is not None and str(value) else None
            return None
        if hasattr(hit, "field"):
            try:
                source = hit.field("_source")
            except Exception:  # noqa: BLE001
                return None
            if source is None:
                return None
            if isinstance(source, dict):
                value = source.get("chunk_id")
                return str(value) if value is not None and str(value) else None
            if hasattr(source, "get"):
                try:
                    value = source.get("chunk_id")
                except Exception:  # noqa: BLE001
                    return None
                if value is None and hasattr(source, "path"):
                    try:
                        value = source.path("chunk_id")
                    except Exception:  # noqa: BLE001
                        return None
                if value is None:
                    return None
                if hasattr(value, "asText"):
                    text = value.asText()
                    return text or None
                return str(value) if value is not None and str(value) else None
        return None

    @staticmethod
    def _hit_score(hit: Any) -> float:
        if isinstance(hit, dict):
            score = hit.get("_score", 0.0)
            return float(score) if isinstance(score, (int, float)) else 0.0
        if hasattr(hit, "field"):
            try:
                score = hit.field("_score")
            except Exception:  # noqa: BLE001
                return 0.0
            return float(score) if isinstance(score, (int, float)) else 0.0
        return 0.0
