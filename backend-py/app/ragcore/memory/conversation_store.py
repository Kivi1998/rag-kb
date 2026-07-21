"""会话消息的读写抽象。

对应 Java 版 `ragcore/conversation/ConversationStore.java`。
写直达(Redis 热路径滑动窗口 + MongoDB 长期存档同步写入,两者都成功才算完成)。

注意: Redis 不可达时,读操作 SHALL 优雅降级(fail-open,退化为无历史单轮问答),
不得抛异常中断问答流程;这与 JWT 黑名单场景的 fail-close 语义不同,实现时不应混用
同一套异常处理策略。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from app.ragcore.memory.chat_message import ChatMessage


@runtime_checkable
class ConversationStore(Protocol):
    async def append_message(
        self,
        organization_id: UUID,
        kb_id: UUID,
        member_id: UUID,
        session_id: UUID,
        message: ChatMessage,
    ) -> None: ...

    async def recent_raw_messages(
        self, organization_id: UUID, session_id: UUID
    ) -> list[ChatMessage]: ...

    async def archived_messages(
        self, organization_id: UUID, kb_id: UUID, member_id: UUID, session_id: UUID
    ) -> list[ChatMessage]: ...

    async def delete_session(
        self, organization_id: UUID, kb_id: UUID, member_id: UUID, session_id: UUID
    ) -> None: ...
