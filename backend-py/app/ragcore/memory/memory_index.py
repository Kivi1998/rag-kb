"""统一语义记忆检索端口。

对应 Java 版 `ragcore/conversation/MemoryIndex.java`。
短期会话内历史(`session_id` 过滤)与长期跨会话画像(`member_id` 过滤)复用同一套
向量检索实现,只是过滤条件不同。`scored_memory_record` 是附带 ES `_score` 的命中
条目,供新条目语义去重阈值判断。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from app.ragcore.memory.memory_record import MemoryRecord


@dataclass(frozen=True, slots=True)
class ScoredMemoryRecord:
    """`MemoryIndex` 检索结果附带的 ES 相关度分数记录。"""

    record: MemoryRecord
    score: float


@runtime_checkable
class MemoryIndex(Protocol):
    async def upsert(self, record: MemoryRecord, vector: list[float]) -> None: ...

    async def delete(self, memory_id: str) -> None: ...

    async def delete_by_session(self, organization_id: UUID, session_id: UUID) -> None: ...

    async def search_session_history(
        self,
        organization_id: UUID,
        session_id: UUID,
        query_vector: list[float],
        top_k: int,
    ) -> list[ScoredMemoryRecord]: ...

    async def search_profile_items(
        self,
        organization_id: UUID,
        member_id: UUID,
        query_vector: list[float],
        top_k: int,
    ) -> list[ScoredMemoryRecord]: ...
