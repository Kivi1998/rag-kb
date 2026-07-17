package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.ragcore.model.Chunk;
import com.diit.ragkb.ragcore.model.RetrievedChunk;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;

/** 默认权重 1.0/1.0 必须与未加权版本数学等价（现状回归安全）；非默认权重按公式生效。 */
class RrfFusionTest {

    @Test
    void defaultWeightsAreMathematicallyEquivalentToUnweightedFuse() {
        Chunk a = chunk("a");
        Chunk b = chunk("b");
        List<RetrievedChunk> bm25 = List.of(new RetrievedChunk(a, 1, null, null, null, null),
                new RetrievedChunk(b, 2, null, null, null, null));
        List<RetrievedChunk> vector = List.of(new RetrievedChunk(b, null, 1, null, null, null));

        List<RetrievedChunk> unweighted = RrfFusion.fuse(bm25, vector);
        List<RetrievedChunk> explicitDefault = RrfFusion.fuse(bm25, vector, 1.0, 1.0);

        assertEquals(unweighted.stream().map(RetrievedChunk::rrfScore).toList(),
                explicitDefault.stream().map(RetrievedChunk::rrfScore).toList());
        assertEquals(unweighted.stream().map(c -> c.chunk().id()).toList(),
                explicitDefault.stream().map(c -> c.chunk().id()).toList());
    }

    @Test
    void higherBm25WeightRanksBm25OnlyChunkAboveVectorOnlyChunkOfEqualRank() {
        Chunk bm25Hit = chunk("bm25-hit");
        Chunk vectorHit = chunk("vector-hit");
        List<RetrievedChunk> bm25 = List.of(new RetrievedChunk(bm25Hit, 1, null, null, null, null));
        List<RetrievedChunk> vector = List.of(new RetrievedChunk(vectorHit, null, 1, null, null, null));

        // 等权重下两者排名并列（同为 rank=1），排序稳定但分数相同。
        List<RetrievedChunk> equalWeighted = RrfFusion.fuse(bm25, vector, 1.0, 1.0);
        assertEquals(equalWeighted.get(0).rrfScore(), equalWeighted.get(1).rrfScore());

        // 精确检索型：调高 bm25Weight，bm25-only 候选分数应严格高于 vector-only 候选。
        List<RetrievedChunk> bm25Favored = RrfFusion.fuse(bm25, vector, 1.3, 0.7);
        assertEquals("bm25-hit", bm25Favored.get(0).chunk().id());
        assertEquals(true, bm25Favored.get(0).rrfScore() > bm25Favored.get(1).rrfScore());
    }

    private Chunk chunk(String id) {
        UUID orgId = UUID.randomUUID();
        return new Chunk(id, orgId, UUID.randomUUID(), UUID.randomUUID(), 0, id, List.of(), "test", null, 1, 1,
                "text", id, java.util.Map.of());
    }
}
