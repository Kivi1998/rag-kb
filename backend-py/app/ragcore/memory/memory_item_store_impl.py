"""`MemoryItemStore` 实现。

对应 Java 版 `ragcore/conversation/impl/MemoryItemStoreImpl.java`。
MongoDB 存权威数据(importance/access_count/last_accessed_at),统一记忆索引(ES)负责
语义检索候选池,读时计算衰减,不需要定时批处理任务。

**多租户**: ES 查询已带 org_id + member_id 过滤,回包后逐条 MongoDB 二次比对
`organization_id` / `member_id`;`find_similar_existing` 与 `top_k_for_generation`
都做这一道纵深防御。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from app.ragcore.memory.memory_index import MemoryIndex
from app.ragcore.memory.memory_item_document import MemoryItemDocument
from app.ragcore.memory.memory_item_repository import MemoryItemRepository
from app.ragcore.memory.memory_item_store import MemoryItemStore
from app.ragcore.memory.memory_record import MemoryRecord
from app.ragcore.memory.memory_type import MemoryType

logger = logging.getLogger(__name__)

# 语义去重阈值:语义是"原始余弦相似度",而非 ES 返回的 `_score`。
# ES 对 cosine 相似度的 dense_vector 字段做了 `_score = (1 + cosine) / 2` 归一化
# (保证非负),并非原始余弦值本身;直接拿原始余弦阈值与 `_score` 比较会让判定阈值变松
# (原始余弦 ~0.84 就会产生 `_score` ≈ 0.92),因此比较前必须先换算成 `_score` 量纲。
DEDUP_COSINE_SIMILARITY_THRESHOLD: float = 0.92


def _dedup_score_threshold() -> float:
    return (1.0 + DEDUP_COSINE_SIMILARITY_THRESHOLD) / 2.0


def _belongs_to_tenant(
    document: MemoryItemDocument, organization_id: UUID, member_id: UUID
) -> bool:
    """二次校验租户归属,不完全信任上游 ES kNN 过滤的结果——防止索引 bug、映射迁移
    等原因导致跨租户的 memory_id 被返回后,仍从 MongoDB 里读出并使用另一租户的画像数据。"""
    return (
        document.organization_id == organization_id and document.member_id == member_id
    )


class MemoryItemStoreImpl(MemoryItemStore):
    def __init__(
        self,
        memory_index: MemoryIndex,
        memory_item_repository: MemoryItemRepository,
        decay_half_life_days: int = 30,
    ) -> None:
        self._index = memory_index
        self._repo = memory_item_repository
        self._half_life_days = max(1, decay_half_life_days)

    async def find_similar_existing(
        self,
        organization_id: UUID,
        member_id: UUID,
        candidate_vector: list[float],
    ) -> Optional[MemoryItemDocument]:
        scored = await self._index.search_profile_items(
            organization_id, member_id, candidate_vector, 1
        )
        if not scored or scored[0].score < _dedup_score_threshold():
            return None
        memory_id = scored[0].record.memory_id
        document = await self._repo.find_by_id(memory_id)
        if document is None:
            return None
        if not _belongs_to_tenant(document, organization_id, member_id):
            return None
        return document

    async def create_item(
        self,
        organization_id: UUID,
        member_id: UUID,
        type: str,
        content: str,
        initial_importance: float,
        vector: list[float],
        source_session_id: UUID | None,
    ) -> MemoryItemDocument:
        now = datetime.now(timezone.utc)
        document = MemoryItemDocument(
            member_id=member_id,
            organization_id=organization_id,
            type=type,
            content=content,
            importance=initial_importance,
            access_count=0,
            last_accessed_at=now,
            created_at=now,
            source_session_id=source_session_id,
        )
        document = await self._repo.save(document)
        if document.id:
            record = MemoryRecord(
                memory_id=document.id,
                organization_id=organization_id,
                member_id=member_id,
                session_id=None,
                type=MemoryType.PROFILE_ITEM,
                content=content,
                created_at=now,
            )
            await self._index.upsert(record, vector)
        return document

    async def top_k_for_generation(
        self,
        organization_id: UUID,
        member_id: UUID,
        query_vector: list[float],
        top_k: int,
    ) -> list[MemoryItemDocument]:
        # 候选池比 topK 更大:ES 只负责"语义相关",最终排序还要叠加 effective_importance。
        candidate_pool = max(top_k * 3, 10)
        scored = await self._index.search_profile_items(
            organization_id, member_id, query_vector, candidate_pool
        )
        candidate_ids = [c.record.memory_id for c in scored]
        now = datetime.now(timezone.utc)
        # 批量 findAllById 替代逐条 findById,避免每次问答产生 N 次串行 Mongo 往返;
        # 同时二次校验租户归属,不完全信任上游 ES 过滤结果。
        all_documents = await self._repo.find_all_by_id(candidate_ids)
        filtered: list[MemoryItemDocument] = [
            doc for doc in all_documents if _belongs_to_tenant(doc, organization_id, member_id)
        ]
        filtered.sort(
            key=lambda doc: _effective_importance(doc, now, self._half_life_days),
            reverse=True,
        )
        selected = filtered[:top_k]
        # 命中巩固:更新 accessCount/lastAccessedAt,批量落库
        for doc in selected:
            doc.access_count += 1
            doc.last_accessed_at = now
        if selected:
            await self._repo.save_all(selected)
        return selected

    async def cleanup_stale(self, cutoff: datetime, importance_threshold: float) -> int:
        stale = await self._repo.find_stale(cutoff, importance_threshold)
        for document in stale:
            await self._index.delete(document.id or "")
            await self._repo.delete_by_id(document.id or "")
        return len(stale)


def _effective_importance(
    document: MemoryItemDocument, now: datetime, half_life_days: int
) -> float:
    """effective_importance = importance × decay(now - lastAccessedAt),decay 用半衰期指数衰减。"""
    if document.last_accessed_at is None:
        document.last_accessed_at = document.created_at
    days_since_access = (
        (now - document.last_accessed_at).total_seconds() / 86400.0
    )
    half_life = max(1.0, float(half_life_days))
    decay = 0.5 ** (days_since_access / half_life)
    return document.importance * decay
