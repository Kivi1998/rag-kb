"""用户画像条目(`memory_items`)的读写端口。

对应 Java 版 `ragcore/conversation/MemoryItemStore.java`。
语义去重、读时衰减、检索命中巩固。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol, runtime_checkable
from uuid import UUID

from app.ragcore.memory.memory_item_document import MemoryItemDocument


@runtime_checkable
class MemoryItemStore(Protocol):
    async def find_similar_existing(
        self,
        organization_id: UUID,
        member_id: UUID,
        candidate_vector: list[float],
    ) -> Optional[MemoryItemDocument]: ...

    async def create_item(
        self,
        organization_id: UUID,
        member_id: UUID,
        type: str,
        content: str,
        initial_importance: float,
        vector: list[float],
        source_session_id: UUID | None,
    ) -> MemoryItemDocument: ...

    async def top_k_for_generation(
        self,
        organization_id: UUID,
        member_id: UUID,
        query_vector: list[float],
        top_k: int,
    ) -> list[MemoryItemDocument]: ...

    async def cleanup_stale(self, cutoff: datetime, importance_threshold: float) -> int: ...
