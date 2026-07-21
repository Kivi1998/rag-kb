"""把超出 token 预算的最旧消息压缩成一段摘要的端口。对应 Java 版 `ragcore/conversation/ConversationSummarizer.java`。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.ragcore.memory.chat_message import ChatMessage


@runtime_checkable
class ConversationSummarizer(Protocol):
    async def summarize(self, messages_to_compress: list[ChatMessage]) -> str: ...
