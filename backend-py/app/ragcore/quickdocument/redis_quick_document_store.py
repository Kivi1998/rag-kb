"""`QuickDocumentStore` 的 Redis 实现。

对应 Java 版 `ragcore/quickdocument/RedisQuickDocumentStore.java`。
- 内容 key 独立 TTL(`quickdoc:content:{docId}`),`quickdoc_session_idle_hours` 控制
  (默认 2h,允许自然过期)
- 会话索引用 Set(`quickdoc:session-index:{sessionId}`)。Set 不支持单成员 TTL,
  采用"读时自愈"策略: 每次 `find_all_by_session` 都会对索引里的 docId 做存在性检查,
  清理已过期内容对应的陈旧引用,不依赖索引 Set 自身 TTL 与内容 key 精确同步。

复用 `app.ragcore.memory.redis_client` 的连接约定: `settings.rag_quick_document_redis_database`
  独立逻辑 DB(DB 2),不复用 JWT 黑名单(DB 0)或会话记忆(DB 1)的连接。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

import redis.asyncio as redis

from app.core.config import Settings, settings as default_settings
from app.ragcore.quickdocument.quick_document import QuickDocument
from app.ragcore.quickdocument.quick_document_store import QuickDocumentStore

logger = logging.getLogger(__name__)


def _content_key(doc_id: UUID) -> str:
    return f"quickdoc:content:{doc_id}"


def _session_index_key(session_id: UUID) -> str:
    return f"quickdoc:session-index:{session_id}"


class RedisQuickDocumentStore(QuickDocumentStore):
    def __init__(
        self,
        client: redis.Redis,
        cfg: Settings | None = None,
        ttl_hours: int | None = None,
    ) -> None:
        cfg = cfg or default_settings
        self._client = client
        self._ttl_seconds = (
            ttl_hours if ttl_hours is not None else cfg.rag_quick_document_ttl_hours
        ) * 3600

    async def save(self, document: QuickDocument) -> None:
        payload = json.dumps(_to_payload(document), ensure_ascii=False)
        await _await(self._client.set(_content_key(document.doc_id), payload, ex=self._ttl_seconds))
        index_key = _session_index_key(document.session_id)
        await _await(self._client.sadd(index_key, str(document.doc_id)))
        await _await(self._client.expire(index_key, self._ttl_seconds))

    async def find_all_by_session(self, session_id: UUID) -> list[QuickDocument]:
        index_key = _session_index_key(session_id)
        members = await _await(self._client.smembers(index_key))
        if not members:
            return []
        result: list[QuickDocument] = []
        for raw in members:
            doc_id = raw if isinstance(raw, str) else raw.decode("utf-8")
            try:
                doc_uuid = UUID(doc_id)
            except ValueError:
                continue
            payload = await _await(self._client.get(_content_key(doc_uuid)))
            if payload is None:
                # 内容 key 已过期,索引里的引用是陈旧的,清理掉不影响本次调用结果
                await _await(self._client.srem(index_key, doc_id))
                continue
            try:
                result.append(_from_payload(json.loads(payload)))
            except (json.JSONDecodeError, ValueError) as ex:
                logger.warning("Redis 临时文档反序列化失败,跳过: %s", ex)
        return result

    async def delete(self, session_id: UUID, doc_id: UUID) -> None:
        await _await(self._client.delete(_content_key(doc_id)))
        await _await(self._client.srem(_session_index_key(session_id), str(doc_id)))

    async def touch(self, session_id: UUID, doc_ids: list[UUID]) -> None:
        if not doc_ids:
            return
        # 续期命中文档及其所属会话索引的 TTL;未命中的文档不受影响,按原 TTL 自然过期
        for doc_id in doc_ids:
            await _await(self._client.expire(_content_key(doc_id), self._ttl_seconds))
        await _await(self._client.expire(_session_index_key(session_id), self._ttl_seconds))


# ---- 序列化辅助 --------------------------------------------------------

def _to_payload(document: QuickDocument) -> dict[str, Any]:
    return {
        "docId": str(document.doc_id),
        "sessionId": str(document.session_id),
        "filename": document.filename,
        "content": document.content,
        "characterCount": document.character_count,
        "createdAt": document.created_at.isoformat(),
    }


def _from_payload(payload: dict[str, Any]) -> QuickDocument:
    created_at_raw = payload.get("createdAt")
    if isinstance(created_at_raw, str):
        created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
    else:
        raise ValueError(f"createdAt 字段类型非法: {type(created_at_raw).__name__}")
    return QuickDocument(
        doc_id=UUID(str(payload["docId"])),
        session_id=UUID(str(payload["sessionId"])),
        filename=str(payload["filename"]),
        content=str(payload["content"]),
        character_count=int(payload["characterCount"]),
        created_at=created_at,
    )


async def _await(value):
    if hasattr(value, "__await__"):
        return await value
    return value
