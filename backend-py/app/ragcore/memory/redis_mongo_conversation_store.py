"""`ConversationStore` 的 Redis + MongoDB 组合实现。

对应 Java 版 `ragcore/conversation/impl/RedisMongoConversationStore.java`。
- Redis 只保留最近 `REDIS_WINDOW_SIZE` 条原始消息(有界,避免无限增长),TTL 略大于
  `rag_memory_session_idle_hours`,允许自然过期;
- MongoDB 保留全部历史(长期存档);
- 写直达: MongoDB 先写(权威持久化),Redis 后写(热路径,失败只记日志)。

**多租户**: `archived_messages` 强制带 `kb_id` 校验(2026-07-15 漏洞修复),
`delete_session` 同样带 `kb_id`,防止同组织同成员跨知识库读取/删除对话历史。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

import redis.asyncio as redis

from app.ragcore.memory.chat_message import ChatMessage
from app.ragcore.memory.chat_message_document import ChatMessageDocument
from app.ragcore.memory.chat_message_repository import ChatMessageRepository
from app.ragcore.memory.conversation_store import ConversationStore
from app.ragcore.memory.redis_client import get_memory_redis
from app.ragcore.model import Citation

logger = logging.getLogger(__name__)

REDIS_WINDOW_SIZE: int = 50
REDIS_KEY_TTL_SECONDS: int = 3 * 60 * 60  # 略长于 IDLE 上限(2 小时),允许自然过期


def _redis_key(session_id: UUID) -> str:
    return f"chat:session:{session_id}:messages"


class RedisMongoConversationStore(ConversationStore):
    def __init__(
        self,
        memory_redis: redis.Redis | None = None,
        chat_message_repository: ChatMessageRepository | None = None,
    ) -> None:
        self._redis = memory_redis or get_memory_redis()
        self._repo = chat_message_repository or ChatMessageRepository()

    async def append_message(
        self,
        organization_id: UUID,
        kb_id: UUID,
        member_id: UUID,
        session_id: UUID,
        message: ChatMessage,
    ) -> None:
        # 写直达: MongoDB 先写(权威),Redis 后写(热路径,失败只记日志)。
        document = ChatMessageDocument.from_chat_message(
            session_id=session_id,
            organization_id=organization_id,
            kb_id=kb_id,
            member_id=member_id,
            message=message,
        )
        await self._repo.save(document)
        try:
            key = _redis_key(session_id)
            payload = _serialize(message)
            await _await(self._redis.rpush(key, payload))
            await _await(self._redis.ltrim(key, -REDIS_WINDOW_SIZE, -1))
            await _await(self._redis.expire(key, REDIS_KEY_TTL_SECONDS))
        except Exception as ex:  # noqa: BLE001 - Redis 失败不影响持久化结果
            logger.warning(
                "会话记忆 Redis 写入失败,本轮消息已持久化到 MongoDB,不影响问答: sessionId=%s, ex=%s",
                session_id, ex,
            )

    async def recent_raw_messages(
        self, organization_id: UUID, session_id: UUID
    ) -> list[ChatMessage]:
        try:
            raw_list = await _await(self._redis.lrange(_redis_key(session_id), 0, -1))
        except Exception as ex:  # noqa: BLE001 - fail-open
            logger.warning(
                "会话记忆 Redis 读取失败,本轮问答退化为无短期记忆的单轮问答: sessionId=%s, ex=%s",
                session_id, ex,
            )
            return []
        if not raw_list:
            return []
        messages: list[ChatMessage] = []
        for raw in raw_list:
            try:
                messages.append(_deserialize(raw))
            except Exception as ex:  # noqa: BLE001
                logger.warning("Redis 滑动窗口单条反序列化失败,跳过: %s", ex)
        return messages

    async def archived_messages(
        self,
        organization_id: UUID,
        kb_id: UUID,
        member_id: UUID,
        session_id: UUID,
    ) -> list[ChatMessage]:
        # 2026-07-15 漏洞修复: URL 里携带的 kb_id 必须参与 MongoDB 查询,防止同
        # 组织同成员跨知识库读取对话历史。
        documents = await self._repo.find_by_session(
            session_id=session_id,
            organization_id=organization_id,
            kb_id=kb_id,
            member_id=member_id,
        )
        return [d.to_chat_message() for d in documents]

    async def delete_session(
        self,
        organization_id: UUID,
        kb_id: UUID,
        member_id: UUID,
        session_id: UUID,
    ) -> None:
        # MongoDB 是权威存储,删除失败必须让调用方感知(不吞异常)。
        await self._repo.delete_by_session(
            session_id=session_id,
            organization_id=organization_id,
            kb_id=kb_id,
            member_id=member_id,
        )
        try:
            await _await(self._redis.delete(_redis_key(session_id)))
        except Exception as ex:  # noqa: BLE001 - Redis key 有 TTL,失败不影响正确性
            logger.warning(
                "会话删除时 Redis 滑动窗口 key 清理失败,将依赖 TTL 自然过期: sessionId=%s, ex=%s",
                session_id, ex,
            )


async def _await(value):
    """redis.asyncio 在非 pipeline 模式下直接返回结果,在 pipeline 模式下返回 awaitable。
    统一在这里 await——pipeline 不在本实现使用,出现就当异常传播。"""
    if hasattr(value, "__await__"):
        return await value
    return value


# ---- 序列化辅助 --------------------------------------------------------

def _serialize(message: ChatMessage) -> str:
    """Redis 短期滑动窗口只喂给指代消解/摘要压缩用(只取 role/content 拼文本),不需要
    citations——序列化前去掉,避免每条 assistant 消息白白把最多 8 条引用(含最长 500 字
    的原文片段)写进 Redis 却从来不会被读取。"""
    minimal = ChatMessage(
        role=message.role,
        content=message.content,
        created_at=message.created_at,
        key_fact=message.key_fact,
        citations=None,
    )
    return json.dumps(_to_payload(minimal), ensure_ascii=False, default=_json_default)


def _deserialize(raw: str) -> ChatMessage:
    obj: Any = json.loads(raw)
    created = obj.get("createdAt")
    if isinstance(created, str):
        created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
    else:
        raise ValueError(f"createdAt 字段类型非法: {type(created).__name__}")
    return ChatMessage(
        role=str(obj["role"]),
        content=str(obj["content"]),
        created_at=created_dt,
        key_fact=bool(obj.get("keyFact", False)),
        citations=None,
    )


def _to_payload(message: ChatMessage) -> dict[str, Any]:
    return {
        "role": message.role,
        "content": message.content,
        "keyFact": message.key_fact,
        "createdAt": message.created_at.isoformat(),
    }


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Citation):
        return {
            "documentId": str(value.document_id) if value.document_id else None,
            "documentName": value.document_name,
            "headingPath": list(value.heading_path),
            "snippet": value.snippet,
            "pageNo": value.page_no,
            "lineStart": value.line_start,
            "lineEnd": value.line_end,
            "score": value.score,
        }
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"无法序列化为 JSON: {type(value).__name__}")
