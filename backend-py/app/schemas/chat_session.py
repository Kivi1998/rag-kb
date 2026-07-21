"""会话 DTO。对应 Java 版 ChatSessionController 的响应形状:
createSession 返回 Map.of("sessionId", ...)、listSessions 返回 ChatSessionService.ChatSessionSummary
列表、getMessages 返回 ragcore/conversation/ChatMessage 列表。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.ragcore.memory.chat_message import ChatMessage
from app.schemas.citation import CitationOut


class CreateSessionResponse(BaseModel):
    session_id: UUID = Field(..., alias="sessionId")

    model_config = {"populate_by_name": True}


class ChatSessionSummaryOut(BaseModel):
    session_id: UUID = Field(..., alias="sessionId")
    title: str | None = None
    last_active_at: datetime = Field(..., alias="lastActiveAt")

    model_config = {"populate_by_name": True}


class ChatMessageOut(BaseModel):
    role: str
    content: str
    created_at: datetime = Field(..., alias="createdAt")
    key_fact: bool = Field(default=False, alias="keyFact")
    citations: list[CitationOut] | None = None

    model_config = {"populate_by_name": True}

    @staticmethod
    def from_domain(message: ChatMessage) -> "ChatMessageOut":
        return ChatMessageOut(
            role=message.role,
            content=message.content,
            createdAt=message.created_at,
            keyFact=message.key_fact,
            citations=(
                [CitationOut.from_domain(c) for c in message.citations]
                if message.citations is not None
                else None
            ),
        )
