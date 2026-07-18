package com.diit.ragkb.ragcore.retrieval;

/** 向量数据库返回的最小候选，禁止携带未校验的正文或引用元数据。 */
public record VectorHit(String chunkId, int rank, double score) {
    public VectorHit {
        if (chunkId == null || chunkId.isBlank() || rank <= 0 || !Double.isFinite(score)) {
            throw new IllegalArgumentException("向量命中必须包含 chunkId、正数排名和有限分数");
        }
    }
}
