"""统一记忆索引(`rag_memory_v1`)的原生 ES 适配器。

对应 Java 版 `ragcore/conversation/impl/ElasticsearchMemoryIndex.java`。
复用 chunk 索引同一个 ES 集群(同一个 `AsyncElasticsearch` 实例),只是索引名不同,
比照 `ElasticsearchChunkIndex` 的实现模式。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from elasticsearch import AsyncElasticsearch

from app.core.config import Settings, settings as default_settings
from app.ragcore.index.exceptions import ElasticsearchIndexException
from app.ragcore.memory.memory_index import MemoryIndex, ScoredMemoryRecord
from app.ragcore.memory.memory_record import MemoryRecord
from app.ragcore.memory.memory_type import MemoryType

logger = logging.getLogger(__name__)


def _memory_record_from_source(source: dict[str, Any]) -> MemoryRecord | None:
    try:
        session_id_raw = source.get("session_id")
        session_id = UUID(str(session_id_raw)) if session_id_raw else None
        created_raw = source.get("created_at")
        if not created_raw:
            raise ValueError("缺少 created_at")
        if isinstance(created_raw, datetime):
            created_at = created_raw
        elif isinstance(created_raw, str):
            created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
        else:
            raise ValueError(f"created_at 字段类型非法: {type(created_raw).__name__}")
        return MemoryRecord(
            memory_id=str(source["memory_id"]),
            organization_id=UUID(str(source["org_id"])),
            member_id=UUID(str(source["member_id"])),
            session_id=session_id,
            type=MemoryType(str(source["memory_type"])),
            content=str(source["content"]),
            created_at=created_at,
        )
    except (KeyError, ValueError, TypeError) as ex:
        logger.warning("ES 记忆索引单条反序列化失败,跳过: %s", ex)
        return None


class ElasticsearchMemoryIndex(MemoryIndex):
    def __init__(
        self,
        es_client: AsyncElasticsearch,
        cfg: Settings | None = None,
        index_name: str | None = None,
        vector_dimensions: int | None = None,
    ) -> None:
        self._es = es_client
        cfg = cfg or default_settings
        self._index_name = index_name or cfg.rag_memory_es_index_name
        self._vector_dimensions = vector_dimensions or cfg.rag_es_vector_dimensions

    async def ensure_index(self) -> None:
        """幂等创建索引与 mapping;重复调用不会覆盖既有生产 mapping。"""
        try:
            exists = await self._es.indices.exists(index=self._index_name)
        except Exception as ex:  # noqa: BLE001
            raise ElasticsearchIndexException("检查记忆索引失败") from ex
        if exists:
            return
        try:
            await self._es.indices.create(
                index=self._index_name,
                mappings={
                    "dynamic": "strict",
                    "properties": {
                        "memory_id": {"type": "keyword"},
                        "org_id": {"type": "keyword"},
                        "member_id": {"type": "keyword"},
                        "session_id": {"type": "keyword"},
                        "memory_type": {"type": "keyword"},
                        "content": {"type": "text"},
                        "content_vector": {
                            "type": "dense_vector",
                            "dims": self._vector_dimensions,
                            "index": True,
                            "similarity": "cosine",
                        },
                        "created_at": {"type": "date"},
                    },
                },
            )
        except Exception as ex:  # noqa: BLE001
            # 并发启动时另一实例已创建;再次确认即可,与 Java 版处理 400 一致
            if await self._index_exists():
                return
            raise ElasticsearchIndexException("创建记忆索引失败") from ex

    async def _index_exists(self) -> bool:
        try:
            return bool(await self._es.indices.exists(index=self._index_name))
        except Exception:  # noqa: BLE001
            return False

    async def upsert(self, record: MemoryRecord, vector: list[float]) -> None:
        if not vector or len(vector) != self._vector_dimensions:
            raise ValueError(f"向量维度必须为 {self._vector_dimensions}")
        source = {
            "memory_id": record.memory_id,
            "org_id": str(record.organization_id),
            "member_id": str(record.member_id),
            "session_id": str(record.session_id) if record.session_id is not None else None,
            "memory_type": record.type.name,
            "content": record.content,
            "content_vector": list(vector),
            "created_at": record.created_at.isoformat(),
        }
        try:
            await self._es.index(
                index=self._index_name,
                id=record.memory_id,
                document=source,
                refresh=False,
            )
        except Exception as ex:  # noqa: BLE001
            raise ElasticsearchIndexException("写入记忆索引失败") from ex

    async def delete(self, memory_id: str) -> None:
        from elasticsearch import NotFoundError  # type: ignore

        try:
            await self._es.delete(index=self._index_name, id=memory_id)
        except NotFoundError:
            return
        except Exception as ex:  # noqa: BLE001
            raise ElasticsearchIndexException("删除记忆条目失败") from ex

    async def delete_by_session(self, organization_id: UUID, session_id: UUID) -> None:
        """过滤条件与 `search_session_history` 保持一致(org_id + session_id +
        memory_type=SESSION_MESSAGE),不裸传 sessionId,避免跨租户误删。"""
        query = {
            "bool": {
                "filter": [
                    {"term": {"org_id": str(organization_id)}},
                    {"term": {"session_id": str(session_id)}},
                    {"term": {"memory_type": MemoryType.SESSION_MESSAGE.name}},
                ]
            }
        }
        try:
            await self._es.delete_by_query(
                index=self._index_name, query=query, conflicts="proceed", refresh=False
            )
        except Exception as ex:  # noqa: BLE001
            raise ElasticsearchIndexException("删除会话记忆条目失败") from ex

    async def search_session_history(
        self,
        organization_id: UUID,
        session_id: UUID,
        query_vector: list[float],
        top_k: int,
    ) -> list[ScoredMemoryRecord]:
        filters = [
            {"term": {"org_id": str(organization_id)}},
            {"term": {"session_id": str(session_id)}},
            {"term": {"memory_type": MemoryType.SESSION_MESSAGE.name}},
        ]
        return await self._search(filters, query_vector, top_k)

    async def search_profile_items(
        self,
        organization_id: UUID,
        member_id: UUID,
        query_vector: list[float],
        top_k: int,
    ) -> list[ScoredMemoryRecord]:
        filters = [
            {"term": {"org_id": str(organization_id)}},
            {"term": {"member_id": str(member_id)}},
            {"term": {"memory_type": MemoryType.PROFILE_ITEM.name}},
        ]
        return await self._search(filters, query_vector, top_k)

    async def _search(
        self,
        filters: list[dict[str, Any]],
        query_vector: list[float],
        top_k: int,
    ) -> list[ScoredMemoryRecord]:
        if not query_vector or len(query_vector) != self._vector_dimensions:
            raise ValueError(f"查询向量维度必须为 {self._vector_dimensions}")
        body = {
            "size": top_k,
            "_source": [
                "memory_id", "org_id", "member_id", "session_id",
                "memory_type", "content", "created_at",
            ],
            "knn": {
                "field": "content_vector",
                "query_vector": list(query_vector),
                "k": top_k,
                "num_candidates": max(50, top_k * 3),
                "filter": filters,
            },
        }
        try:
            response = await self._es.search(index=self._index_name, body=body)
        except Exception as ex:  # noqa: BLE001
            raise ElasticsearchIndexException("记忆索引检索失败") from ex
        return self._parse_hits(response)

    @staticmethod
    def _parse_hits(response: Any) -> list[ScoredMemoryRecord]:
        if response is None:
            return []
        if isinstance(response, dict):
            payload = response.get("hits", {})
        elif hasattr(response, "body") and isinstance(response.body, dict):
            payload = response.body.get("hits", {})
        else:
            return []
        if not isinstance(payload, dict):
            return []
        hits = payload.get("hits")
        if not isinstance(hits, list):
            return []
        result: list[ScoredMemoryRecord] = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            source = hit.get("_source")
            if not isinstance(source, dict):
                continue
            record = _memory_record_from_source(source)
            if record is None:
                continue
            score_raw = hit.get("_score")
            try:
                score = float(score_raw) if score_raw is not None else 0.0
            except (TypeError, ValueError):
                score = 0.0
            result.append(ScoredMemoryRecord(record=record, score=score))
        return result
