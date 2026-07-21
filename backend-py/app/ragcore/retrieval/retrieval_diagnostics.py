"""检索过程的非正文诊断信息，供审计与告警使用。对应 Java 版 `ragcore/retrieval/RetrievalDiagnostics.java`。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetrievalDiagnostics:
    bm25_candidate_count: int = 0
    vector_candidate_count: int = 0
    fused_candidate_count: int = 0
    embedding_fallback: bool = False
    rerank_fallback: bool = False

    def __post_init__(self) -> None:
        if self.bm25_candidate_count < 0:
            raise ValueError("bm25_candidate_count 不能为负数")
        if self.vector_candidate_count < 0:
            raise ValueError("vector_candidate_count 不能为负数")
        if self.fused_candidate_count < 0:
            raise ValueError("fused_candidate_count 不能为负数")

    @staticmethod
    def empty() -> "RetrievalDiagnostics":
        return RetrievalDiagnostics(0, 0, 0, False, False)
