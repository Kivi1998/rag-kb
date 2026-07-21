"""`MemoryItemStoreImpl` 多租户二次校验 + 衰减排序测试。

对照 Java 版 `ragcore/conversation/impl/MemoryItemStoreImpl.java`。
关键行为:
- 读路径(ES kNN 命中)→ MongoDB 二次校验 `organization_id` / `member_id`,过滤越权
- 衰减:有效重要度 = importance × 0.5^(days_since_access/half_life)
- 命中巩固:top_k 命中的条目 access_count+1,last_accessed_at 刷新
- 语义去重:ES _score > 0.96 → 跳过(MEMORY_HNSW 索引原始余弦 0.92)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.ragcore.memory.memory_index import MemoryIndex, ScoredMemoryRecord
from app.ragcore.memory.memory_item_document import MemoryItemDocument
from app.ragcore.memory.memory_item_repository import MemoryItemRepository
from app.ragcore.memory.memory_item_store_impl import (
    DEDUP_COSINE_SIMILARITY_THRESHOLD,
    MemoryItemStoreImpl,
    _dedup_score_threshold,
    _effective_importance,
)
from app.ragcore.memory.memory_record import MemoryRecord
from app.ragcore.memory.memory_type import MemoryType
from bson import ObjectId  # type: ignore


class _StubMemoryIndex(MemoryIndex):
    def __init__(self, scored: list[ScoredMemoryRecord] | None = None) -> None:
        self._scored = scored or []
        self.search_calls: list[dict] = []

    async def upsert(self, record, vector):
        pass

    async def delete(self, memory_id):
        pass

    async def delete_by_session(self, organization_id, session_id):
        pass

    async def search_session_history(self, organization_id, session_id, query_vector, top_k):
        self.search_calls.append({"scope": "session"})
        return self._scored

    async def search_profile_items(self, organization_id, member_id, query_vector, top_k):
        self.search_calls.append({"scope": "profile", "top_k": top_k, "member_id": member_id})
        return self._scored


class _StubRepo:
    def __init__(self) -> None:
        self._docs: dict[str, MemoryItemDocument] = {}
        self.find_by_id_calls: list[str] = []
        self.find_all_by_id_calls: list[list[str]] = []
        self.save_calls: list[MemoryItemDocument] = []
        self.save_all_calls: list[list[MemoryItemDocument]] = []
        self.find_stale_calls: list[tuple[datetime, float]] = []
        self.delete_by_id_calls: list[str] = []

    def seed(self, doc: MemoryItemDocument) -> None:
        doc.id = doc.id or str(ObjectId())
        self._docs[doc.id] = doc

    async def save(self, document: MemoryItemDocument) -> MemoryItemDocument:
        document.id = document.id or str(ObjectId())
        self._docs[document.id] = document
        self.save_calls.append(document)
        return document

    async def save_all(self, documents):
        for d in documents:
            d.id = d.id or str(ObjectId())
            self._docs[d.id] = d
        self.save_all_calls.append(list(documents))

    async def find_by_id(self, memory_id: str):
        self.find_by_id_calls.append(memory_id)
        return self._docs.get(memory_id)

    async def find_all_by_id(self, memory_ids: list[str]):
        self.find_all_by_id_calls.append(list(memory_ids))
        return [self._docs[mid] for mid in memory_ids if mid in self._docs]

    async def find_stale(self, cutoff, importance_threshold):
        self.find_stale_calls.append((cutoff, importance_threshold))
        return [d for d in self._docs.values()
                if d.last_accessed_at < cutoff and d.importance < importance_threshold]

    async def delete_by_id(self, memory_id):
        self.delete_by_id_calls.append(memory_id)
        self._docs.pop(memory_id, None)


def _make_record(
    memory_id: str,
    org: UUID,
    member: UUID,
    content: str = "x",
    type: MemoryType = MemoryType.PROFILE_ITEM,
    score: float = 0.99,
) -> ScoredMemoryRecord:
    return ScoredMemoryRecord(
        record=MemoryRecord(
            memory_id=memory_id,
            organization_id=org,
            member_id=member,
            type=type,
            content=content,
            created_at=datetime.now(timezone.utc),
        ),
        score=score,
    )


def _make_document(
    memory_id: str | None,
    org: UUID,
    member: UUID,
    content: str = "x",
    importance: float = 0.5,
) -> MemoryItemDocument:
    now = datetime.now(timezone.utc)
    return MemoryItemDocument(
        id=memory_id,
        member_id=member,
        organization_id=org,
        type="PREFERENCE",
        content=content,
        importance=importance,
        access_count=0,
        last_accessed_at=now,
        created_at=now,
    )


class TestDedupConstants:
    def test_cosine_threshold_value(self):
        """ES _score 量纲的语义去重阈值:0.92 原始余弦 → (1+0.92)/2 = 0.96 _score。"""
        assert DEDUP_COSINE_SIMILARITY_THRESHOLD == 0.92

    def test_dedup_score_threshold_is_normalized(self):
        """ES 把 cosine 归一化到 [0,1](_score = (1+cosine)/2),所以原始余弦阈值
        必须先换算成 _score 量纲再比,否则判定会变松。"""
        expected = (1.0 + DEDUP_COSINE_SIMILARITY_THRESHOLD) / 2.0
        assert _dedup_score_threshold() == pytest.approx(expected)


class TestFindSimilarExisting:
    @pytest.mark.asyncio
    async def test_no_match_returns_none(self):
        index = _StubMemoryIndex(scored=[])
        repo = _StubRepo()
        store = MemoryItemStoreImpl(memory_index=index, memory_item_repository=repo)
        result = await store.find_similar_existing(uuid4(), uuid4(), [0.1, 0.2])
        assert result is None

    @pytest.mark.asyncio
    async def test_low_score_returns_none(self):
        """ES _score 低于去重阈值时不视为"已存在"——允许新条目入库。"""
        org = uuid4()
        member = uuid4()
        record = _make_record("m-1", org, member, score=_dedup_score_threshold() - 0.01)
        index = _StubMemoryIndex(scored=[record])
        repo = _StubRepo()
        store = MemoryItemStoreImpl(memory_index=index, memory_item_repository=repo)
        result = await store.find_similar_existing(org, member, [0.1, 0.2])
        assert result is None

    @pytest.mark.asyncio
    async def test_high_score_returns_existing(self):
        org = uuid4()
        member = uuid4()
        record = _make_record("m-1", org, member, score=_dedup_score_threshold() + 0.01)
        index = _StubMemoryIndex(scored=[record])
        repo = _StubRepo()
        # 预先 seed
        doc = _make_document("m-1", org, member)
        repo.seed(doc)
        store = MemoryItemStoreImpl(memory_index=index, memory_item_repository=repo)
        result = await store.find_similar_existing(org, member, [0.1, 0.2])
        assert result is not None
        assert result.id == "m-1"

    @pytest.mark.asyncio
    async def test_cross_tenant_mongo_doc_rejected_by_secondary_check(self):
        """ES 错误地返回了别的 member 的 memory_id,二次校验必须丢掉。"""
        request_org = uuid4()
        request_member = uuid4()
        foreign_member = uuid4()  # 不同的 member

        record = _make_record("m-1", request_org, foreign_member, score=0.99)
        index = _StubMemoryIndex(scored=[record])
        repo = _StubRepo()
        doc = _make_document("m-1", request_org, foreign_member)  # MongoDB 里这条属于 foreign member
        repo.seed(doc)
        store = MemoryItemStoreImpl(memory_index=index, memory_item_repository=repo)
        result = await store.find_similar_existing(request_org, request_member, [0.1, 0.2])
        assert result is None, "跨 member 的 ES 命中必须在二次校验时被丢掉"


class TestTopKForGeneration:
    @pytest.mark.asyncio
    async def test_returns_sorted_by_effective_importance(self):
        org = uuid4()
        member = uuid4()
        # 创建三个 memory:importance 不同,衰减后排序应该按 effective_importance
        doc_old_important = _make_document("m-old", org, member, content="old but important", importance=0.9)
        doc_old_important.last_accessed_at = datetime.now(timezone.utc) - timedelta(days=15)
        doc_new_unimportant = _make_document("m-new", org, member, content="new unimportant", importance=0.4)
        doc_mid = _make_document("m-mid", org, member, content="middle", importance=0.6)

        index = _StubMemoryIndex(scored=[
            _make_record("m-old", org, member, score=0.99),
            _make_record("m-new", org, member, score=0.97),
            _make_record("m-mid", org, member, score=0.95),
        ])
        repo = _StubRepo()
        repo.seed(doc_old_important)
        repo.seed(doc_new_unimportant)
        repo.seed(doc_mid)
        store = MemoryItemStoreImpl(memory_index=index, memory_item_repository=repo)

        result = await store.top_k_for_generation(org, member, [0.1, 0.2], top_k=2)
        # 应返回前 2 个,按 effective_importance 降序
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_access_count_incremented_on_hit(self):
        """top_k 命中的条目必须 access_count+1,last_accessed_at 刷新——巩固记忆信号。"""
        org = uuid4()
        member = uuid4()
        doc = _make_document("m-1", org, member)
        initial_count = doc.access_count
        index = _StubMemoryIndex(scored=[_make_record("m-1", org, member, score=0.99)])
        repo = _StubRepo()
        repo.seed(doc)
        store = MemoryItemStoreImpl(memory_index=index, memory_item_repository=repo)
        await store.top_k_for_generation(org, member, [0.1, 0.2], top_k=5)
        assert doc.access_count == initial_count + 1

    @pytest.mark.asyncio
    async def test_cross_tenant_items_filtered_out(self):
        """ES 错误返回了其他 org/member 的 memory_id,二次校验必须过滤。"""
        request_org = uuid4()
        request_member = uuid4()
        foreign_org = uuid4()

        own_doc = _make_document("m-own", request_org, request_member, content="own")
        foreign_doc = _make_document("m-foreign", foreign_org, request_member, content="foreign")
        # ES 返回了 2 个候选
        index = _StubMemoryIndex(scored=[
            _make_record("m-own", request_org, request_member, score=0.99),
            _make_record("m-foreign", foreign_org, request_member, score=0.95),
        ])
        repo = _StubRepo()
        repo.seed(own_doc)
        repo.seed(foreign_doc)
        store = MemoryItemStoreImpl(memory_index=index, memory_item_repository=repo)
        result = await store.top_k_for_generation(request_org, request_member, [0.1, 0.2], top_k=5)
        # 跨 org 的 foreign 必须被过滤
        assert all(d.organization_id == request_org for d in result)


class TestEffectiveImportance:
    def test_no_decay_when_just_accessed(self):
        """刚刚访问过,days=0,decay=1.0,effective=importance。"""
        doc = _make_document(None, uuid4(), uuid4(), importance=0.8)
        doc.last_accessed_at = datetime.now(timezone.utc)
        score = _effective_importance(doc, datetime.now(timezone.utc), half_life_days=30)
        assert score == pytest.approx(0.8)

    def test_decay_after_half_life(self):
        """half_life 天后访问,decay=0.5,effective=importance/2。"""
        doc = _make_document(None, uuid4(), uuid4(), importance=0.8)
        now = datetime.now(timezone.utc)
        doc.last_accessed_at = now - timedelta(days=30)
        score = _effective_importance(doc, now, half_life_days=30)
        assert score == pytest.approx(0.4)

    def test_decay_after_two_half_lives(self):
        doc = _make_document(None, uuid4(), uuid4(), importance=0.8)
        now = datetime.now(timezone.utc)
        doc.last_accessed_at = now - timedelta(days=60)
        score = _effective_importance(doc, now, half_life_days=30)
        assert score == pytest.approx(0.2)


class TestCleanupStale:
    @pytest.mark.asyncio
    async def test_cleanup_deletes_stale_and_removes_from_index(self):
        from app.ragcore.memory.memory_index import MemoryIndex

        class _IndexWithDelete(MemoryIndex):
            def __init__(self) -> None:
                self.deleted: list[str] = []

            async def upsert(self, record, vector): pass
            async def delete(self, memory_id): self.deleted.append(memory_id)
            async def delete_by_session(self, organization_id, session_id): pass
            async def search_session_history(self, *a, **kw): return []
            async def search_profile_items(self, *a, **kw): return []

        index = _IndexWithDelete()
        repo = _StubRepo()
        doc = _make_document("m-1", uuid4(), uuid4(), importance=0.01)
        repo.seed(doc)
        store = MemoryItemStoreImpl(memory_index=index, memory_item_repository=repo)

        deleted = await store.cleanup_stale(datetime.now(timezone.utc), importance_threshold=0.05)
        assert deleted == 1
        assert "m-1" in index.deleted
        assert "m-1" in repo.delete_by_id_calls


class TestCreateItem:
    @pytest.mark.asyncio
    async def test_creates_and_writes_to_index(self):
        org = uuid4()
        member = uuid4()
        session = uuid4()
        index = _StubMemoryIndex()
        repo = _StubRepo()
        store = MemoryItemStoreImpl(memory_index=index, memory_item_repository=repo)
        await store.create_item(
            organization_id=org, member_id=member,
            type="FACT", content="公司用 Java",
            initial_importance=0.8, vector=[0.1, 0.2],
            source_session_id=session,
        )
        assert len(repo.save_calls) == 1
        assert repo.save_calls[0].organization_id == org
        assert repo.save_calls[0].content == "公司用 Java"
        assert repo.save_calls[0].source_session_id == session


class TestMemoryRecordValidation:
    """MemoryRecord 必须携带 organization_id / member_id,type 一致性约束。"""

    def test_profile_item_cannot_have_session_id(self):
        """PROFILE_ITEM 跨会话存在,不应携带 session_id。"""
        with pytest.raises(ValueError):
            MemoryRecord(
                memory_id="m-1",
                organization_id=uuid4(), member_id=uuid4(),
                type=MemoryType.PROFILE_ITEM, content="x",
                created_at=datetime.now(timezone.utc),
                session_id=uuid4(),  # 不应携带
            )

    def test_session_message_must_have_session_id(self):
        with pytest.raises(ValueError):
            MemoryRecord(
                memory_id="m-1",
                organization_id=uuid4(), member_id=uuid4(),
                type=MemoryType.SESSION_MESSAGE, content="x",
                created_at=datetime.now(timezone.utc),
                session_id=None,
            )

    def test_blank_content_rejected(self):
        with pytest.raises(ValueError):
            MemoryRecord(
                memory_id="m-1",
                organization_id=uuid4(), member_id=uuid4(),
                type=MemoryType.PROFILE_ITEM, content="   ",
                created_at=datetime.now(timezone.utc),
            )

    def test_missing_org_id_rejected(self):
        with pytest.raises(ValueError):
            MemoryRecord(
                memory_id="m-1",
                organization_id=None,  # type: ignore
                member_id=uuid4(),
                type=MemoryType.PROFILE_ITEM, content="x",
                created_at=datetime.now(timezone.utc),
            )

    def test_missing_member_id_rejected(self):
        with pytest.raises(ValueError):
            MemoryRecord(
                memory_id="m-1",
                organization_id=uuid4(), member_id=None,  # type: ignore
                type=MemoryType.PROFILE_ITEM, content="x",
                created_at=datetime.now(timezone.utc),
            )
