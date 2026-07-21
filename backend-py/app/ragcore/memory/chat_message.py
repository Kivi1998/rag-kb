"""一轮对话里的一条消息(用户提问或助手回答),跨 Redis/MongoDB/API 层复用的值对象。

对应 Java 版 `ragcore/conversation/ChatMessage.java`。
`citations` 只有 assistant 角色、且这个字段上线后新产生的消息才会有值;user 消息和
旧消息该字段为 None,前端按"没有引用"处理,不做历史回填。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from app.ragcore.model import Citation

ROLE_USER: str = "user"
ROLE_ASSISTANT: str = "assistant"
VALID_ROLES: frozenset[str] = frozenset({ROLE_USER, ROLE_ASSISTANT})


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str
    content: str
    created_at: datetime
    key_fact: bool = False
    citations: tuple[Citation, ...] | None = None

    def __post_init__(self) -> None:
        if not self.role or not self.role.strip():
            raise ValueError("ChatMessage.role 不能为空")
        if self.role not in VALID_ROLES:
            raise ValueError(f"ChatMessage.role 必须是 {sorted(VALID_ROLES)} 之一,收到 {self.role!r}")
        if not self.content or not self.content.strip():
            raise ValueError("ChatMessage.content 不能为空")
        if self.created_at is None:
            raise ValueError("ChatMessage.created_at 不能为空")
        if self.citations is not None:
            object.__setattr__(self, "citations", tuple(self.citations))

    @staticmethod
    def user(content: str, created_at: datetime) -> "ChatMessage":
        return ChatMessage(role=ROLE_USER, content=content, created_at=created_at)

    @staticmethod
    def assistant(
        content: str,
        created_at: datetime,
        citations: Iterable[Citation] | None = None,
    ) -> "ChatMessage":
        cit_tuple: tuple[Citation, ...] | None = None
        if citations is not None:
            cit_tuple = tuple(citations)
        return ChatMessage(
            role=ROLE_ASSISTANT,
            content=content,
            created_at=created_at,
            citations=cit_tuple,
        )
