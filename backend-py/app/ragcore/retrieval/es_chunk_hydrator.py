"""使用受 org/kb 过滤保护的 ES 批量查询补齐向量命中,并恢复输入 ID 顺序。

对应 Java 版 `ragcore/retrieval/ElasticsearchChunkHydrator.java`。
多租户第三道纵深防御:即便 ES 查询的 bool.filter 已经带 org_id/kb_id 过滤,
回程结果会再次逐条比对 chunk.organization_id/knowledge_base_id。
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from elasticsearch import AsyncElasticsearch

from app.core.config import Settings, settings as default_settings
from app.ragcore.index.exceptions import ElasticsearchIndexException
from app.ragcore.model import Chunk
from app.ragcore.retrieval.chunk_hydrator import ChunkHydrator
from app.ragcore.retrieval.es_chunk_document_mapper import SOURCE_FIELDS, to_chunk

logger = logging.getLogger(__name__)


class ElasticsearchChunkHydrator(ChunkHydrator):
    def __init__(
        self,
        es_client: AsyncElasticsearch,
        cfg: Settings | None = None,
        index_name: str | None = None,
    ) -> None:
        self._es = es_client
        cfg = cfg or default_settings
        self._index_name = index_name or cfg.rag_es_index_name

    async def find_by_chunk_ids(
        self,
        organization_id: UUID,
        knowledge_base_id: UUID,
        chunk_ids: list[str],
    ) -> list[Chunk]:
        if organization_id is None or knowledge_base_id is None:
            raise ValueError("Chunk 补齐必须携带组织与知识库边界")
        if not chunk_ids:
            return []

        ids: list[str] = []
        seen: set[str] = set()
        for cid in chunk_ids:
            if not cid:
                continue
            if cid in seen:
                continue
            seen.add(cid)
            ids.append(cid)
        if not ids:
            return []

        body: dict[str, Any] = {
            "size": len(ids),
            "_source": list(SOURCE_FIELDS),
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"org_id": str(organization_id)}},
                        {"term": {"kb_id": str(knowledge_base_id)}},
                        {"term": {"retrieval_ready": True}},
                        {"terms": {"chunk_id": ids}},
                    ]
                }
            },
        }
        try:
            response = await self._es.search(index=self._index_name, body=body)
        except Exception as ex:  # noqa: BLE001 - 包装为可识别异常
            raise ElasticsearchIndexException("ES Chunk 补齐失败") from ex

        hits = self._extract_hits(response)
        safe: dict[str, Chunk] = {}
        for hit in hits:
            try:
                source = self._hit_source(hit)
                chunk = to_chunk(source)
            except ElasticsearchIndexException as ex:
                logger.warning("ES Chunk 补齐单条反序列化失败,跳过: %s", ex)
                continue
            # 第三道纵深防御
            if (
                chunk.organization_id == organization_id
                and chunk.knowledge_base_id == knowledge_base_id
                and chunk.id in seen
            ):
                safe[chunk.id] = chunk

        # 恢复输入 ID 顺序;不可找到的 ID 直接略过(交给孤儿指标计数)
        return [safe[cid] for cid in ids if cid in safe]

    @staticmethod
    def _extract_hits(response: Any) -> list[dict[str, Any]]:
        if response is None:
            return []
        if isinstance(response, dict):
            payload = response.get("hits", {})
        elif hasattr(response, "body") and isinstance(response.body, dict):
            payload = response.body.get("hits", {})
        else:
            payload = {}
        hits_obj = payload.get("hits", []) if isinstance(payload, dict) else []
        if not isinstance(hits_obj, list):
            return []
        result: list[dict[str, Any]] = []
        for hit in hits_obj:
            if isinstance(hit, dict):
                result.append(hit)
            else:
                result.append({"_source": hit})
        return result

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
