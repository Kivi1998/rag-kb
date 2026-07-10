package com.diit.ragkb.ragcore.model;

/** 混合检索与重排过程中的候选分块及其可解释分数。 */
public record RetrievedChunk(
        Chunk chunk,
        Integer bm25Rank,
        Integer vectorRank,
        Double rrfScore,
        Double rerankScore,
        Double finalScore
) {
}
