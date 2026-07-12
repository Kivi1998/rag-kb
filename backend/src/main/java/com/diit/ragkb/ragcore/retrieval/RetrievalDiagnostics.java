package com.diit.ragkb.ragcore.retrieval;

/** 检索过程的非正文诊断信息，供审计与告警使用。 */
public record RetrievalDiagnostics(
        int bm25CandidateCount,
        int vectorCandidateCount,
        int fusedCandidateCount,
        boolean embeddingFallback,
        boolean rerankFallback
) {
    public RetrievalDiagnostics {
        if (bm25CandidateCount < 0 || vectorCandidateCount < 0 || fusedCandidateCount < 0) {
            throw new IllegalArgumentException("候选数量不能为负数");
        }
    }

    public static RetrievalDiagnostics empty() {
        return new RetrievalDiagnostics(0, 0, 0, false, false);
    }
}
