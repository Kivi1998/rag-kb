"""Milvus HNSW 召回,只返回 Chunk ID、得分和名次。

对应 Java 版 `ragcore/retrieval/MilvusVectorCandidateSource.java`。
多租户过滤: filter 字符串中参数化注入 org_id/kb_id/retrieval_ready=true,
document_ids 非空时叠加 `document_id in {document_ids}`——这是第一道租户隔离,
向量 ID 回流到 ES 的 `ChunkHydrator` 时还有第二、三道(详见 ElasticsearchChunkHydrator)。

注意: 2026-07-15 修复过一个 16384 真实漏洞,位于 `MilvusVectorIndex.setVisibility()`,
不在本检索路径。本类只做 `search()`,与该 bug 无关。
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from pymilvus import MilvusClient  # type: ignore

from app.core.config import Settings, settings as default_settings
from app.ragcore.index.exceptions import MilvusVectorException
from app.ragcore.index.milvus_collection_manager import MilvusCollectionManager
from app.ragcore.retrieval.vector_candidate_source import VectorCandidateSource
from app.ragcore.retrieval.vector_hit import VectorHit
from app.ragcore.retrieval.vector_search_request import VectorSearchRequest

logger = logging.getLogger(__name__)


class MilvusVectorCandidateSource(VectorCandidateSource):
    def __init__(
        self,
        client: MilvusClient,
        cfg: Settings | None = None,
        database_name: str | None = None,
        collection_name: str | None = None,
        vector_dimensions: int | None = None,
        metric_type: str | None = None,
        search_ef: int | None = None,
    ) -> None:
        self._client = client
        cfg = cfg or default_settings
        self._database_name = database_name or cfg.rag_milvus_database
        self._collection_name = collection_name or cfg.rag_milvus_collection
        self._vector_dimensions = vector_dimensions or cfg.rag_milvus_vector_dimensions
        self._metric_type = metric_type or cfg.rag_milvus_metric_type
        self._search_ef = search_ef or cfg.rag_milvus_search_ef

    async def search(self, request: VectorSearchRequest) -> list[VectorHit]:
        if request is None:
            raise ValueError("Milvus 向量查询不能为空")
        if len(request.query_vector) != self._vector_dimensions:
            raise ValueError(f"Milvus 查询向量维度必须为 {self._vector_dimensions}")

        filter_expr = self._build_filter(request)

        # pymilvus 2.6 MilvusClient.search() 是同步 API,需要包到 to_thread 避免阻塞
        # asyncio 事件循环;本检索路径可能在多请求并发下被命中。
        try:
            import asyncio

            raw_hits = await asyncio.to_thread(
                self._client.search,
                collection_name=self._collection_name,
                data=[list(request.query_vector)],
                anns_field=MilvusCollectionManager.EMBEDDING,
                limit=request.top_k,
                filter=filter_expr,
                output_fields=[MilvusCollectionManager.CHUNK_ID],
                search_params={"metric_type": self._metric_type, "ef": max(self._search_ef, request.top_k)},
            )
        except Exception as ex:  # noqa: BLE001
            raise MilvusVectorException("Milvus 向量检索失败") from ex

        if not raw_hits:
            return []
        return self._convert_hits(raw_hits[0] if isinstance(raw_hits, list) else raw_hits)

    # ---- 内部实现 --------------------------------------------------------

    @staticmethod
    def _build_filter(request: VectorSearchRequest) -> str:
        """参数化构造 Milvus filter 表达式。

        org_id / kb_id 是 UUID 字符串(可控输入),document_ids 是 UUID 列表(可控输入),
        直接用 f-string 插值即可——Milvus filter 解析器对 UUID 字符串字面量是安全的。
        """
        org_id = str(request.organization_id)
        kb_id = str(request.knowledge_base_id)
        filter_expr = (
            f'{MilvusCollectionManager.ORG_ID} == "{org_id}" and '
            f'{MilvusCollectionManager.KB_ID} == "{kb_id}" and '
            f'{MilvusCollectionManager.RETRIEVAL_READY} == true'
        )
        if request.document_ids:
            doc_list = ", ".join(f'"{str(d)}"' for d in request.document_ids)
            filter_expr += f" and {MilvusCollectionManager.DOCUMENT_ID} in [{doc_list}]"
        return filter_expr

    @staticmethod
    def _convert_hits(hits: Any) -> list[VectorHit]:
        if hits is None:
            return []
        result: list[VectorHit] = []
        for rank, hit in enumerate(hits, start=1):
            chunk_id = MilvusVectorCandidateSource._hit_chunk_id(hit)
            score = MilvusVectorCandidateSource._hit_score(hit)
            if chunk_id is None or score is None:
                continue
            result.append(VectorHit(chunk_id=chunk_id, rank=rank, score=score))
        return result

    @staticmethod
    def _hit_chunk_id(hit: Any) -> str | None:
        if hit is None:
            return None
        # 1) 显式 output_fields 投影
        if isinstance(hit, dict):
            for key in ("chunk_id", "id", "primary_key"):
                if key in hit and hit[key] is not None and str(hit[key]):
                    return str(hit[key])
            # pymilvus 也常用 entity 嵌套
            entity = hit.get("entity") if isinstance(hit, dict) else None
            if isinstance(entity, dict):
                for key in ("chunk_id", "id", "primary_key"):
                    if key in entity and entity[key] is not None and str(entity[key]):
                        return str(entity[key])
            return None
        # 对象式 hit
        for attr in ("id", "primary_key"):
            if hasattr(hit, attr):
                value = getattr(hit, attr, None)
                if value is not None and str(value):
                    return str(value)
        entity = getattr(hit, "entity", None)
        if entity is not None:
            if isinstance(entity, dict):
                value = entity.get("chunk_id")
                if value is not None and str(value):
                    return str(value)
            elif hasattr(entity, "get"):
                try:
                    value = entity.get("chunk_id")
                except Exception:  # noqa: BLE001
                    value = None
                if value is not None and str(value):
                    return str(value)
        return None

    @staticmethod
    def _hit_score(hit: Any) -> float | None:
        if hit is None:
            return None
        if isinstance(hit, dict):
            score = hit.get("distance") or hit.get("score")
            try:
                return float(score) if score is not None else None
            except (TypeError, ValueError):
                return None
        if hasattr(hit, "distance"):
            try:
                return float(hit.distance)
            except (TypeError, ValueError):
                return None
        if hasattr(hit, "score"):
            try:
                return float(hit.score)
            except (TypeError, ValueError):
                return None
        return None
