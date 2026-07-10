package com.diit.ragkb.ragcore.retrieval;

/** 混合检索与重排阶段的查询参数。 */
public record RetrievalOptions(int candidateLimit, int resultLimit, boolean rerank) {

    public RetrievalOptions {
        if (candidateLimit <= 0 || resultLimit <= 0 || resultLimit > candidateLimit) {
            throw new IllegalArgumentException("候选数必须大于等于结果数，且两者都大于 0");
        }
    }

    public static RetrievalOptions defaults() {
        return new RetrievalOptions(50, 8, true);
    }
}
