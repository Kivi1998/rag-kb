"""查询审计快照 `QueryAuditSnapshot` 数据契约与工厂测试。

对应 Java 版 `ragcore/audit/QueryAuditSnapshot.java`。
关键不变量:
- 必填字段(trace_id / organization_id / knowledge_base_id / member_id)缺失或为空时直接拒绝
- retrieval_latency_ms 不可为负数(数据库 CheckConstraint 也是同样下限)
- `from_retrieval` 工厂:chunk_ids 全部保留 / document_ids 按出现顺序去重 / final_scores 只留非 None
- `before_retrieval` 工厂:等价于"空 retrieval 阶段"的快照,延迟固定为 0
- frozen dataclass:实例字段不可改写,确保审计行在落库前不会被外部 mutate
"""

from __future__ import annotations

import dataclasses
from uuid import UUID, uuid4

import pytest

from app.ragcore.audit.query_audit_snapshot import QueryAuditSnapshot
from app.ragcore.model import Chunk, RetrievedChunk
from app.ragcore.retrieval.retrieval_diagnostics import RetrievalDiagnostics


def _make_chunk(
    chunk_id: str = "chunk-1",
    document_id: UUID | None = None,
    organization_id: UUID | None = None,
    knowledge_base_id: UUID | None = None,
) -> Chunk:
    return Chunk(
        id=chunk_id,
        organization_id=organization_id,
        knowledge_base_id=knowledge_base_id,
        document_id=document_id,
        ordinal=0,
        content="dummy",
    )


def _make_retrieved(
    chunk_id: str = "chunk-1",
    document_id: UUID | None = None,
    final_score: float | None = 0.5,
    organization_id: UUID | None = None,
    knowledge_base_id: UUID | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=_make_chunk(
            chunk_id=chunk_id,
            document_id=document_id,
            organization_id=organization_id,
            knowledge_base_id=knowledge_base_id,
        ),
        final_score=final_score,
    )


def _snapshot_kwargs(**overrides) -> dict:
    defaults = dict(
        trace_id="trace-1",
        organization_id=uuid4(),
        knowledge_base_id=uuid4(),
        member_id=uuid4(),
        retrieval_latency_ms=10,
    )
    defaults.update(overrides)
    return defaults


class TestRequiredFieldValidation:
    def test_minimal_valid_construction(self):
        """所有必填字段给出合法值时,应能直接构造。"""
        snap = QueryAuditSnapshot(**_snapshot_kwargs())
        assert snap.trace_id == "trace-1"
        assert snap.chunk_ids == ()
        assert snap.document_ids == ()
        assert snap.final_scores == ()
        assert snap.diagnostics.embedding_fallback is False
        assert snap.refused is False
        assert snap.refusal_reason is None
        assert snap.predicted_intent is None

    def test_blank_trace_id_rejected(self):
        with pytest.raises(ValueError):
            QueryAuditSnapshot(**_snapshot_kwargs(trace_id=""))
        with pytest.raises(ValueError):
            QueryAuditSnapshot(**_snapshot_kwargs(trace_id="   "))
        with pytest.raises(ValueError):
            QueryAuditSnapshot(**_snapshot_kwargs(trace_id="\n\t"))

    def test_none_organization_id_rejected(self):
        with pytest.raises(ValueError):
            QueryAuditSnapshot(**_snapshot_kwargs(organization_id=None))

    def test_none_knowledge_base_id_rejected(self):
        with pytest.raises(ValueError):
            QueryAuditSnapshot(**_snapshot_kwargs(knowledge_base_id=None))

    def test_none_member_id_rejected(self):
        with pytest.raises(ValueError):
            QueryAuditSnapshot(**_snapshot_kwargs(member_id=None))

    def test_negative_latency_rejected(self):
        with pytest.raises(ValueError):
            QueryAuditSnapshot(**_snapshot_kwargs(retrieval_latency_ms=-1))

    def test_zero_latency_accepted(self):
        """`before_retrieval` 路径延迟就是 0,等于号是合法边界。"""
        snap = QueryAuditSnapshot(**_snapshot_kwargs(retrieval_latency_ms=0))
        assert snap.retrieval_latency_ms == 0


class TestImmutability:
    def test_cannot_assign_attribute(self):
        """frozen dataclass:外部赋值必须被拒绝,避免审计行落库前被改。"""
        snap = QueryAuditSnapshot(**_snapshot_kwargs())
        with pytest.raises(dataclasses.FrozenInstanceError):
            snap.trace_id = "forged"

    def test_chunk_ids_tuple_is_immutable(self):
        snap = QueryAuditSnapshot(**_snapshot_kwargs(chunk_ids=("a", "b")))
        assert isinstance(snap.chunk_ids, tuple)
        with pytest.raises((AttributeError, TypeError)):
            snap.chunk_ids[0] = "z"  # type: ignore[index]

    def test_document_ids_tuple_is_immutable(self):
        snap = QueryAuditSnapshot(**_snapshot_kwargs(document_ids=(uuid4(), uuid4())))
        assert isinstance(snap.document_ids, tuple)


class TestFromRetrievalFactory:
    def test_chunk_ids_preserved_in_order(self):
        """chunk_ids 必须按 RetrievedChunk 的输入顺序保留,不要乱序。"""
        org = uuid4()
        kb = uuid4()
        chunks = [
            _make_retrieved(chunk_id=f"c{i}", organization_id=org, knowledge_base_id=kb)
            for i in range(3)
        ]
        snap = QueryAuditSnapshot.from_retrieval(
            trace_id="t",
            organization_id=org,
            knowledge_base_id=kb,
            member_id=uuid4(),
            retrieval_latency_ms=12,
            chunks=chunks,
            diagnostics=RetrievalDiagnostics.empty(),
            refused=False,
            refusal_reason=None,
            predicted_intent=None,
        )
        assert snap.chunk_ids == ("c0", "c1", "c2")

    def test_document_ids_deduped_preserving_order(self):
        """同一文档被多次召回时,document_ids 去重且按首次出现顺序。"""
        org = uuid4()
        kb = uuid4()
        doc_a, doc_b = uuid4(), uuid4()
        chunks = [
            _make_retrieved(chunk_id="c1", document_id=doc_a, organization_id=org, knowledge_base_id=kb),
            _make_retrieved(chunk_id="c2", document_id=doc_b, organization_id=org, knowledge_base_id=kb),
            _make_retrieved(chunk_id="c3", document_id=doc_a, organization_id=org, knowledge_base_id=kb),
            _make_retrieved(chunk_id="c4", document_id=doc_b, organization_id=org, knowledge_base_id=kb),
        ]
        snap = QueryAuditSnapshot.from_retrieval(
            trace_id="t",
            organization_id=org,
            knowledge_base_id=kb,
            member_id=uuid4(),
            retrieval_latency_ms=12,
            chunks=chunks,
            diagnostics=RetrievalDiagnostics.empty(),
            refused=False,
            refusal_reason=None,
            predicted_intent=None,
        )
        # 顺序:首次 doc_a → doc_b;重复项被丢弃
        assert snap.document_ids == (doc_a, doc_b)

    def test_document_ids_none_chunk_dropped(self):
        """document_id 为 None 的 chunk 不会污染 document_ids 列表(模板临时块等场景)。"""
        org = uuid4()
        kb = uuid4()
        chunks = [
            _make_retrieved(chunk_id="c1", document_id=None, organization_id=org, knowledge_base_id=kb),
            _make_retrieved(chunk_id="c2", document_id=uuid4(), organization_id=org, knowledge_base_id=kb),
        ]
        snap = QueryAuditSnapshot.from_retrieval(
            trace_id="t",
            organization_id=org,
            knowledge_base_id=kb,
            member_id=uuid4(),
            retrieval_latency_ms=12,
            chunks=chunks,
            diagnostics=RetrievalDiagnostics.empty(),
            refused=False,
            refusal_reason=None,
            predicted_intent=None,
        )
        assert len(snap.document_ids) == 1

    def test_final_scores_drops_none(self):
        """final_score 为 None 的 chunk(未打分/兜底场景)不写入 final_scores。"""
        org = uuid4()
        kb = uuid4()
        chunks = [
            _make_retrieved(chunk_id="c1", final_score=0.9, organization_id=org, knowledge_base_id=kb),
            _make_retrieved(chunk_id="c2", final_score=None, organization_id=org, knowledge_base_id=kb),
            _make_retrieved(chunk_id="c3", final_score=0.7, organization_id=org, knowledge_base_id=kb),
        ]
        snap = QueryAuditSnapshot.from_retrieval(
            trace_id="t",
            organization_id=org,
            knowledge_base_id=kb,
            member_id=uuid4(),
            retrieval_latency_ms=12,
            chunks=chunks,
            diagnostics=RetrievalDiagnostics.empty(),
            refused=False,
            refusal_reason=None,
            predicted_intent=None,
        )
        assert snap.final_scores == (0.9, 0.7)

    def test_none_chunks_yields_empty_collections(self):
        """chunks=None 时,所有 ID/score 字段安全退化为空 tuple,不是 None。"""
        snap = QueryAuditSnapshot.from_retrieval(
            trace_id="t",
            organization_id=uuid4(),
            knowledge_base_id=uuid4(),
            member_id=uuid4(),
            retrieval_latency_ms=12,
            chunks=None,
            diagnostics=RetrievalDiagnostics.empty(),
            refused=False,
            refusal_reason=None,
            predicted_intent=None,
        )
        assert snap.chunk_ids == ()
        assert snap.document_ids == ()
        assert snap.final_scores == ()

    def test_empty_chunks_iterable_also_safe(self):
        """空可迭代对象同样退化为空 tuple(不应让 None 漏进 tuple 化阶段)。"""
        snap = QueryAuditSnapshot.from_retrieval(
            trace_id="t",
            organization_id=uuid4(),
            knowledge_base_id=uuid4(),
            member_id=uuid4(),
            retrieval_latency_ms=12,
            chunks=[],
            diagnostics=RetrievalDiagnostics.empty(),
            refused=False,
            refusal_reason=None,
            predicted_intent=None,
        )
        assert snap.chunk_ids == ()
        assert snap.document_ids == ()
        assert snap.final_scores == ()

    def test_diagnostics_none_falls_back_to_empty(self):
        """diagnostics=None 时,不能把 None 写进 snapshot,会破坏审计行的诊断字段。"""
        snap = QueryAuditSnapshot.from_retrieval(
            trace_id="t",
            organization_id=uuid4(),
            knowledge_base_id=uuid4(),
            member_id=uuid4(),
            retrieval_latency_ms=12,
            chunks=[],
            diagnostics=None,  # type: ignore[arg-type]
            refused=False,
            refusal_reason=None,
            predicted_intent=None,
        )
        # 必须是空诊断对象(默认值),不是 None
        assert isinstance(snap.diagnostics, RetrievalDiagnostics)
        assert snap.diagnostics.embedding_fallback is False
        assert snap.diagnostics.rerank_fallback is False

    def test_refused_and_refusal_reason_propagate(self):
        """拒答状态与拒答原因必须如实透传到 snapshot,不要在工厂里吞掉。"""
        snap = QueryAuditSnapshot.from_retrieval(
            trace_id="t",
            organization_id=uuid4(),
            knowledge_base_id=uuid4(),
            member_id=uuid4(),
            retrieval_latency_ms=12,
            chunks=[],
            diagnostics=RetrievalDiagnostics.empty(),
            refused=True,
            refusal_reason="参考资料不包含具体答案",
            predicted_intent="semantic",
        )
        assert snap.refused is True
        assert snap.refusal_reason == "参考资料不包含具体答案"
        assert snap.predicted_intent == "semantic"


class TestBeforeRetrievalFactory:
    def test_factory_yields_zero_latency_empty_chunks(self):
        """before_retrieval = 还没跑检索时的占位快照:延迟 0、chunks 空、refused=False。"""
        org = uuid4()
        kb = uuid4()
        member = uuid4()
        snap = QueryAuditSnapshot.before_retrieval(
            trace_id="before-t",
            organization_id=org,
            knowledge_base_id=kb,
            member_id=member,
        )
        assert snap.trace_id == "before-t"
        assert snap.organization_id == org
        assert snap.knowledge_base_id == kb
        assert snap.member_id == member
        assert snap.retrieval_latency_ms == 0
        assert snap.chunk_ids == ()
        assert snap.document_ids == ()
        assert snap.final_scores == ()
        assert snap.refused is False
        assert snap.refusal_reason is None
        assert snap.predicted_intent is None
