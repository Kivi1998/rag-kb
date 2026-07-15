package com.diit.ragkb.ragcore.retrieval;

import java.util.List;
import java.util.UUID;

/**
 * 混合检索与重排阶段的查询参数。
 *
 * <p>{@code documentIds} 非空时，BM25 与向量两路召回都会在租户过滤之外叠加一条
 * document_id 范围过滤，用于"先缩小范围再检索"（如只在用户选中的若干文档内搜索），
 * 既提精度又降延迟。目前仅提供检索层能力，尚无前端入口传入非空值。</p>
 */
public record RetrievalOptions(int candidateLimit, int resultLimit, boolean rerank, List<UUID> documentIds) {

    public RetrievalOptions {
        documentIds = documentIds == null ? List.of() : List.copyOf(documentIds);
        if (candidateLimit <= 0 || resultLimit <= 0 || resultLimit > candidateLimit) {
            throw new IllegalArgumentException("候选数必须大于等于结果数，且两者都大于 0");
        }
    }

    public RetrievalOptions(int candidateLimit, int resultLimit, boolean rerank) {
        this(candidateLimit, resultLimit, rerank, List.of());
    }

    public static RetrievalOptions defaults() {
        return new RetrievalOptions(50, 8, true, List.of());
    }
}
