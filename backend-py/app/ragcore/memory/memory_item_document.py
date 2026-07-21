"""MongoDB `memory_items` 集合的文档模型。

对应 Java 版 `ragcore/conversation/MemoryItemDocument.java`。
`importance`/`access_count`/`last_accessed_at` 供遗忘机制读时衰减计算。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class MemoryItemDocument:
    """MongoDB `memory_items` 集合文档:用户画像条目(偏好/事实/长期目标)。"""

    member_id: UUID
    organization_id: UUID
    type: str
    content: str
    importance: float
    access_count: int
    last_accessed_at: datetime
    created_at: datetime
    source_session_id: UUID | None = None
    id: str | None = None

    def __post_init__(self) -> None:
        if self.member_id is None or self.organization_id is None:
            raise ValueError("MemoryItemDocument 必须携带 member_id 与 organization_id")
        if not self.type or not self.content:
            raise ValueError("MemoryItemDocument type 与 content 不能为空")
        if self.created_at is None:
            raise ValueError("MemoryItemDocument created_at 不能为空")
        if self.last_accessed_at is None:
            self.last_accessed_at = self.created_at
