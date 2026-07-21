"""统一记忆索引(`rag_memory_v1`)里的一条记录。对应 Java 版 `ragcore/conversation/MemoryRecord.java`。

`session_id` 非空时代表短期会话内消息(`MemoryType.SESSION_MESSAGE`),
为空时代表跨会话的长期画像条目(`MemoryType.PROFILE_ITEM`)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.ragcore.memory.memory_type import MemoryType


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    memory_id: str
    organization_id: UUID
    member_id: UUID
    type: MemoryType
    content: str
    created_at: datetime
    session_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.organization_id is None or self.member_id is None:
            raise ValueError("MemoryRecord.organization_id / member_id 不能为空")
        if self.type is None:
            raise ValueError("MemoryRecord.type 不能为空")
        if not self.content or not self.content.strip():
            raise ValueError("MemoryRecord.content 不能为空")
        if self.type == MemoryType.PROFILE_ITEM and self.session_id is not None:
            raise ValueError("画像条目 (PROFILE_ITEM) 不应携带 session_id")
        if self.type == MemoryType.SESSION_MESSAGE and self.session_id is None:
            raise ValueError("会话消息 (SESSION_MESSAGE) 必须携带 session_id")
