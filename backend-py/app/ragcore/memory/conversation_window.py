"""滑动窗口组装结果。对应 Java 版 `ragcore/conversation/ConversationWindow.java` record。

`summary` 非空时代表触发了摘要压缩(替换掉最旧的部分消息),`recent_messages` 是保留的
原文(最近若干轮 + 关键事实消息,未被压缩)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from app.ragcore.memory.chat_message import ChatMessage


@dataclass(frozen=True, slots=True)
class ConversationWindow:
    summary: str | None = None
    recent_messages: tuple[ChatMessage, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "recent_messages", tuple(self.recent_messages or ()))

    @property
    def has_summary(self) -> bool:
        return self.summary is not None and bool(self.summary.strip())

    @staticmethod
    def of(recent_messages: Iterable[ChatMessage], summary: str | None = None) -> "ConversationWindow":
        return ConversationWindow(summary=summary, recent_messages=tuple(recent_messages))
