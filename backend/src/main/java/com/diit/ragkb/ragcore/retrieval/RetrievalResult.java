package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.ragcore.model.RetrievedChunk;

import java.util.List;

/** 检索结果或服务端拒答原因；空结果绝不意味着允许 LLM 自行编造。 */
public record RetrievalResult(List<RetrievedChunk> chunks, String refusalReason, RetrievalDiagnostics diagnostics) {
    public RetrievalResult {
        chunks = chunks == null ? List.of() : List.copyOf(chunks);
        diagnostics = diagnostics == null ? RetrievalDiagnostics.empty() : diagnostics;
        if (!chunks.isEmpty() && refusalReason != null) {
            throw new IllegalArgumentException("命中 chunk 时不能同时设置拒答原因");
        }
    }

    public RetrievalResult(List<RetrievedChunk> chunks, String refusalReason) {
        this(chunks, refusalReason, RetrievalDiagnostics.empty());
    }

    public boolean refused() {
        return refusalReason != null;
    }

    public static RetrievalResult refuse(String reason) {
        return new RetrievalResult(List.of(), reason, RetrievalDiagnostics.empty());
    }

    public static RetrievalResult refuse(String reason, RetrievalDiagnostics diagnostics) {
        return new RetrievalResult(List.of(), reason, diagnostics);
    }
}
