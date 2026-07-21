"""MongoDB `chat_messages` 集合的仓库层。

对应 Java 版 `ragcore/conversation/ChatMessageRepository.java`。
**多租户三重过滤**(纵深防御第三道):
1. MongoDB 查询强制 `sessionId + orgId + memberId`(Java 原版)
2. **新增**: 2026-07-15 漏洞修复——`archivedMessages` 增加 `kbId` 校验,
   防止同组织同成员跨知识库读取对话历史(URL 携带的 `kbId` 必须与会话真实归属 `kbId` 一致)
3. 查询返回后再次显式比对每条文档的 `organization_id` / `kb_id` / `member_id`,
   任何不一致直接丢弃
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from motor.motor_asyncio import AsyncIOMotorCollection  # type: ignore

from app.ragcore.memory.chat_message_document import ChatMessageDocument
from app.ragcore.memory.mongo_client import get_memory_db
from app.ragcore.model import Citation

logger = logging.getLogger(__name__)

COLLECTION_NAME: str = "chat_messages"


class ChatMessageRepository:
    def __init__(self, collection: AsyncIOMotorCollection | None = None) -> None:
        self._collection = collection if collection is not None else self._resolve_collection()

    @staticmethod
    def _resolve_collection() -> AsyncIOMotorCollection | None:
        db = get_memory_db()
        if db is None:
            return None
        return db[COLLECTION_NAME]

    @property
    def collection(self) -> AsyncIOMotorCollection:
        if self._collection is None:
            raise RuntimeError("MongoDB 未配置 (rag_memory_mongo_uri 为空),无法访问 chat_messages")
        return self._collection

    async def save(self, document: ChatMessageDocument) -> str:
        payload = _to_mongo(document)
        result = await self.collection.insert_one(payload)
        return str(result.inserted_id)

    async def find_by_session(
        self,
        session_id: UUID,
        organization_id: UUID,
        kb_id: UUID,
        member_id: UUID,
    ) -> list[ChatMessageDocument]:
        """按会话多租户过滤查询,严格校验 URL `kb_id` 与文档真实 `kb_id` 一致。

        第一道租户过滤: MongoDB 查询本身带 sessionId + orgId + kbId + memberId。
        第二道: 命中结果再显式比对所有四个字段;任何不一致直接丢弃。
        """
        cursor = self.collection.find(
            {
                "sessionId": session_id,
                "organizationId": organization_id,
                "kbId": kb_id,
                "memberId": member_id,
            }
        ).sort("createdAt", 1)
        result: list[ChatMessageDocument] = []
        async for raw in cursor:
            doc = _from_mongo(raw)
            if doc is None:
                continue
            # 纵深防御:不让 ES / MongoDB 任何一层过滤 bug 越过租户边界
            if (
                doc.session_id == session_id
                and doc.organization_id == organization_id
                and doc.kb_id == kb_id
                and doc.member_id == member_id
            ):
                result.append(doc)
        return result

    async def delete_by_session(
        self,
        session_id: UUID,
        organization_id: UUID,
        kb_id: UUID,
        member_id: UUID,
    ) -> int:
        """会话级联删除,严格带四个租户字段避免越权。"""
        result = await self.collection.delete_many(
            {
                "sessionId": session_id,
                "organizationId": organization_id,
                "kbId": kb_id,
                "memberId": member_id,
            }
        )
        return int(result.deleted_count or 0)


def _to_mongo(doc: ChatMessageDocument) -> dict[str, Any]:
    citations: list[dict[str, Any]] | None = None
    if doc.citations is not None:
        citations = [
            {
                "documentId": c.document_id if c.document_id else None,
                "documentName": c.document_name,
                "headingPath": list(c.heading_path),
                "snippet": c.snippet,
                "pageNo": c.page_no,
                "lineStart": c.line_start,
                "lineEnd": c.line_end,
                "score": c.score,
            }
            for c in doc.citations
        ]
    return {
        "sessionId": doc.session_id,
        "organizationId": doc.organization_id,
        "kbId": doc.kb_id,
        "memberId": doc.member_id,
        "role": doc.role,
        "content": doc.content,
        "keyFact": doc.key_fact,
        "createdAt": doc.created_at,
        "citations": citations,
    }


def _from_mongo(raw: dict[str, Any]) -> ChatMessageDocument | None:
    try:
        citations_raw = raw.get("citations")
        citations: list[Citation] | None = None
        if isinstance(citations_raw, list):
            citations = []
            for c in citations_raw:
                if not isinstance(c, dict):
                    continue
                doc_id = c.get("documentId")
                citations.append(
                    Citation(
                        document_id=_as_uuid(doc_id) if doc_id else None,
                        document_name=str(c.get("documentName") or ""),
                        heading_path=tuple(c.get("headingPath") or ()),
                        snippet=str(c.get("snippet") or ""),
                        page_no=c.get("pageNo"),
                        line_start=c.get("lineStart"),
                        line_end=c.get("lineEnd"),
                        score=c.get("score"),
                    )
                )
        return ChatMessageDocument(
            id=str(raw.get("_id")) if raw.get("_id") is not None else None,
            session_id=_as_uuid(raw["sessionId"]),
            organization_id=_as_uuid(raw["organizationId"]),
            kb_id=_as_uuid(raw["kbId"]),
            member_id=_as_uuid(raw["memberId"]),
            role=str(raw["role"]),
            content=str(raw["content"]),
            key_fact=bool(raw.get("keyFact", False)),
            created_at=_parse_datetime(raw.get("createdAt")),
            citations=citations,
        )
    except (KeyError, ValueError, TypeError) as ex:
        logger.warning("MongoDB chat_messages 单条反序列化失败,跳过: %s", ex)
        return None


def _as_uuid(value: Any) -> UUID:
    """兼容原生 BSON UUID(uuidRepresentation=standard 生效时的正常形态)与遗留字符串值。"""
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        # motor 默认是 ISO 8601;带时区/不带时区都要兼容
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as ex:
            raise ValueError(f"无法解析 createdAt: {value!r}") from ex
    raise ValueError(f"createdAt 字段类型非法: {type(value).__name__}")
