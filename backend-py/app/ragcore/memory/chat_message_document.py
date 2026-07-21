"""MongoDB `chat_messages` 集合的文档模型。

对应 Java 版 `ragcore/conversation/ChatMessageDocument.java`。
写直达(Redis 热路径滑动窗口 + MongoDB 长期存档同步写入)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Iterable
from uuid import UUID

from app.ragcore.model import Citation

if TYPE_CHECKING:
    from app.ragcore.memory.chat_message import ChatMessage


@dataclass
class ChatMessageDocument:
    """MongoDB `chat_messages` 集合文档。"""

    session_id: UUID
    organization_id: UUID
    kb_id: UUID
    member_id: UUID
    role: str
    content: str
    created_at: datetime
    key_fact: bool = False
    citations: list[Citation] | None = None
    id: str | None = None

    def __post_init__(self) -> None:
        if self.session_id is None or self.organization_id is None:
            raise ValueError("ChatMessageDocument 必须携带 session_id 与 organization_id")
        if self.kb_id is None:
            raise ValueError("ChatMessageDocument 必须携带 kb_id(2026-07-15 漏洞修复)")
        if self.member_id is None:
            raise ValueError("ChatMessageDocument 必须携带 member_id")
        if not self.role or not self.content or self.created_at is None:
            raise ValueError("ChatMessageDocument role/content/created_at 均不能为空")
        if self.citations is not None:
            self.citations = list(self.citations)

    def to_chat_message(self) -> "ChatMessage":
        """投影为 ChatMessage(忽略持久化字段 id)。"""
        from app.ragcore.memory.chat_message import ChatMessage

        citations_tuple: tuple[Citation, ...] | None = None
        if self.citations is not None:
            citations_tuple = tuple(self.citations)
        return ChatMessage(
            role=self.role,
            content=self.content,
            created_at=self.created_at,
            key_fact=self.key_fact,
            citations=citations_tuple,
        )

    @staticmethod
    def from_chat_message(
        session_id: UUID,
        organization_id: UUID,
        kb_id: UUID,
        member_id: UUID,
        message: "ChatMessage",
    ) -> "ChatMessageDocument":
        return ChatMessageDocument(
            session_id=session_id,
            organization_id=organization_id,
            kb_id=kb_id,
            member_id=member_id,
            role=message.role,
            content=message.content,
            key_fact=message.key_fact,
            created_at=message.created_at,
            citations=list(message.citations) if message.citations is not None else None,
        )
