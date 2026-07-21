"""查询审计快照:单次查询的安全审计快照,只含标识、分数与状态,不含问题或文档正文。

对应 Java 版 `ragcore/audit/QueryAuditSnapshot.java`。
落库时严格按这个 dataclass 序列化,避免把问题正文、模型回答、引用 snippet 等敏感
内容写进审计表——`docs/检索与审计验收.md` 第 3 点明确要求。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable
from uuid import UUID

from app.ragcore.model import RetrievedChunk
from app.ragcore.retrieval.retrieval_diagnostics import RetrievalDiagnostics


@dataclass(frozen=True, slots=True)
class QueryAuditSnapshot:
    trace_id: str
    organization_id: UUID
    knowledge_base_id: UUID
    member_id: UUID
    retrieval_latency_ms: int
    chunk_ids: tuple[str, ...] = field(default_factory=tuple)
    document_ids: tuple[UUID, ...] = field(default_factory=tuple)
    final_scores: tuple[float, ...] = field(default_factory=tuple)
    diagnostics: RetrievalDiagnostics = field(default_factory=RetrievalDiagnostics.empty)
    refused: bool = False
    refusal_reason: str | None = None
    predicted_intent: str | None = None

    def __post_init__(self) -> None:
        if not self.trace_id or not self.trace_id.strip():
            raise ValueError("QueryAuditSnapshot.trace_id 不能为空")
        if self.organization_id is None or self.knowledge_base_id is None or self.member_id is None:
            raise ValueError("QueryAuditSnapshot 必须携带 organization_id / knowledge_base_id / member_id")
        if self.retrieval_latency_ms < 0:
            raise ValueError("retrieval_latency_ms 不能为负数")

    @staticmethod
    def from_retrieval(
        trace_id: str,
        organization_id: UUID,
        knowledge_base_id: UUID,
        member_id: UUID,
        retrieval_latency_ms: int,
        chunks: Iterable[RetrievedChunk] | None,
        diagnostics: RetrievalDiagnostics,
        refused: bool,
        refusal_reason: str | None,
        predicted_intent: str | None,
    ) -> "QueryAuditSnapshot":
        safe_chunks = list(chunks or [])
        chunk_ids = tuple(c.chunk.id for c in safe_chunks)
        # document_ids 去重保序,避免同一文档多次出现拉大审计行长度
        seen: set[UUID] = set()
        document_ids: list[UUID] = []
        for c in safe_chunks:
            doc_id = c.chunk.document_id
            if doc_id is not None and doc_id not in seen:
                seen.add(doc_id)
                document_ids.append(doc_id)
        final_scores: tuple[float, ...] = tuple(
            c.final_score for c in safe_chunks if c.final_score is not None
        )
        return QueryAuditSnapshot(
            trace_id=trace_id,
            organization_id=organization_id,
            knowledge_base_id=knowledge_base_id,
            member_id=member_id,
            retrieval_latency_ms=retrieval_latency_ms,
            chunk_ids=chunk_ids,
            document_ids=tuple(document_ids),
            final_scores=final_scores,
            diagnostics=diagnostics or RetrievalDiagnostics.empty(),
            refused=refused,
            refusal_reason=refusal_reason,
            predicted_intent=predicted_intent,
        )

    @staticmethod
    def before_retrieval(
        trace_id: str,
        organization_id: UUID,
        knowledge_base_id: UUID,
        member_id: UUID,
    ) -> "QueryAuditSnapshot":
        return QueryAuditSnapshot.from_retrieval(
            trace_id=trace_id,
            organization_id=organization_id,
            knowledge_base_id=knowledge_base_id,
            member_id=member_id,
            retrieval_latency_ms=0,
            chunks=[],
            diagnostics=RetrievalDiagnostics.empty(),
            refused=False,
            refusal_reason=None,
            predicted_intent=None,
        )
