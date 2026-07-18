package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.ragcore.model.RetrievedChunk;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** 基于排名而非不同分数量纲的 Reciprocal Rank Fusion。 */
public final class RrfFusion {

    private static final int DEFAULT_RANK_CONSTANT = 60;

    private RrfFusion() {
    }

    public static List<RetrievedChunk> fuse(List<RetrievedChunk> bm25, List<RetrievedChunk> vector) {
        return fuse(bm25, vector, 1.0, 1.0);
    }

    /**
     * 按权重加权的 RRF 融合。{@code bm25Weight}/{@code vectorWeight} 均为 {@code 1.0} 时与
     * 未加权版本数学上完全等价（现状行为不变）。
     */
    public static List<RetrievedChunk> fuse(List<RetrievedChunk> bm25, List<RetrievedChunk> vector,
                                            double bm25Weight, double vectorWeight) {
        Map<String, RetrievedChunk> candidates = new LinkedHashMap<>();
        merge(candidates, bm25, true, bm25Weight, vectorWeight);
        merge(candidates, vector, false, bm25Weight, vectorWeight);
        List<RetrievedChunk> result = new ArrayList<>(candidates.values());
        result.sort(Comparator.comparing(RetrievedChunk::rrfScore, Comparator.nullsLast(Comparator.reverseOrder())));
        return result;
    }

    private static void merge(Map<String, RetrievedChunk> destination, List<RetrievedChunk> source, boolean bm25,
                              double bm25Weight, double vectorWeight) {
        if (source == null) return;
        for (RetrievedChunk item : source) {
            String id = item.chunk().id();
            RetrievedChunk previous = destination.get(id);
            Integer bm25Rank = bm25 ? item.bm25Rank() : previous == null ? null : previous.bm25Rank();
            Integer vectorRank = bm25 ? previous == null ? null : previous.vectorRank() : item.vectorRank();
            double score = bm25Weight * rankScore(bm25Rank) + vectorWeight * rankScore(vectorRank);
            destination.put(id, new RetrievedChunk(item.chunk(), bm25Rank, vectorRank, score, null, score));
        }
    }

    private static double rankScore(Integer rank) {
        return rank == null ? 0 : 1.0 / (DEFAULT_RANK_CONSTANT + rank);
    }
}
