"""检索前把用户问题里的代词/省略指代补全为独立完整问题的端口。

对应 Java 版 `ragcore/conversation/CoreferenceResolver.java`。
调用失败/超时应由实现负责降级(返回原始问题),不应向调用方抛出异常中断问答流程。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.ragcore.memory.chat_message import ChatMessage


@runtime_checkable
class CoreferenceResolver(Protocol):
    async def resolve(self, question: str, history: list[ChatMessage]) -> str: ...
