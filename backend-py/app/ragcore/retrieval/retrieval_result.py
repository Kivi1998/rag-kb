"""检索结果或服务端拒答原因;空结果绝不意味着允许 LLM 自行编造。

对应 Java 版 `ragcore/retrieval/RetrievalResult.java`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from app.ragcore.model import RetrievedChunk
from app.ragcore.retrieval.retrieval_diagnostics import RetrievalDiagnostics


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    chunks: list[RetrievedChunk] = field(default_factory=list)
    refusal_reason: str | None = None
    diagnostics: RetrievalDiagnostics = field(default_factory=RetrievalDiagnostics.empty)

    def __post_init__(self) -> None:
        object.__setattr__(self, "chunks", list(self.chunks or []))
        if not self.chunks and self.refusal_reason is not None:
            return
        if self.chunks and self.refusal_reason is not None:
            raise ValueError("命中 chunk 时不能同时设置拒答原因")

    @property
    def refused(self) -> bool:
        return self.refusal_reason is not None

    @staticmethod
    def refuse(reason: str, diagnostics: RetrievalDiagnostics | None = None) -> "RetrievalResult":
        return RetrievalResult(
            chunks=[],
            refusal_reason=reason,
            diagnostics=diagnostics or RetrievalDiagnostics.empty(),
        )

    @staticmethod
    def of(chunks: Iterable[RetrievedChunk], diagnostics: RetrievalDiagnostics | None = None) -> "RetrievalResult":
        chunk_list = list(chunks)
        return RetrievalResult(
            chunks=chunk_list,
            refusal_reason=None,
            diagnostics=diagnostics
            or RetrievalDiagnostics(len(chunk_list), 0, len(chunk_list), False, False),
        )
