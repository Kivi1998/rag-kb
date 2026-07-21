"""把该用户相关的画像条目组装成一段 System 上下文,供生成阶段拼接。

对应 Java 版 `ragcore/conversation/UserProfileInjector.java`。
只读取 `MemoryItemStore` 检索结果并格式化成文本——**不接触**
`HybridRetriever` / `RetrievalOptions` 等检索组件,画像 SHALL NOT 影响候选池大小、
过滤条件或 RRF 权重,只影响生成阶段的风格与关注点。
"""

from __future__ import annotations

from typing import Iterable
from uuid import UUID

from app.ragcore.memory.memory_item_document import MemoryItemDocument
from app.ragcore.memory.memory_item_store import MemoryItemStore

PROFILE_SYSTEM_HEADER: str = (
    "以下是关于该用户的背景信息,仅供调整回答风格和关注点参考,不代表知识库内容:"
)


class UserProfileInjector:
    def __init__(self, memory_item_store: MemoryItemStore, top_k: int) -> None:
        self._store = memory_item_store
        self._top_k = top_k

    async def build_system_context(
        self,
        organization_id: UUID,
        member_id: UUID,
        query_vector: list[float],
    ) -> str:
        """返回空字符串代表没有相关画像,调用方不应拼接任何 System 上下文。"""
        items = await self._store.top_k_for_generation(
            organization_id, member_id, query_vector, self._top_k
        )
        if not items:
            return ""
        bullets = "\n".join(f"- ({item.type}) {item.content}" for item in items)
        return f"{PROFILE_SYSTEM_HEADER}\n{bullets}"
