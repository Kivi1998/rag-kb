package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.ragcore.embedding.EmbeddingClient;
import com.diit.ragkb.ragcore.model.Chunk;
import com.diit.ragkb.ragcore.model.EmbeddingResult;
import com.diit.ragkb.ragcore.rerank.RerankerClient;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;

import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;

class HybridRetrieverSplitPortsTest {

    @Test
    void splitPortsHydrateVectorIdsBeforeRrf() {
        UUID orgId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        Chunk lexicalChunk = chunk("lexical", orgId, kbId);
        Chunk vectorChunk = chunk("vector", orgId, kbId);
        LexicalCandidateSource lexical = request -> List.of(
                new com.diit.ragkb.ragcore.model.RetrievedChunk(lexicalChunk, 1, null, null, null, 1.0));
        VectorCandidateSource vector = request -> List.of(new VectorHit("vector", 1, 0.9));
        ChunkHydrator hydrator = (org, kb, ids) -> List.of(vectorChunk);
        EmbeddingClient embedding = texts -> new EmbeddingResult("test", List.of(List.of(0.1f, 0.2f)));
        @SuppressWarnings("unchecked")
        ObjectProvider<RerankerClient> reranker = mock(ObjectProvider.class);

        RetrievalResult result = new HybridRetriever(lexical, vector, hydrator, embedding, reranker)
                .retrieveWithDecision(orgId, kbId, "question", new RetrievalOptions(10, 5, false));

        assertEquals(2, result.chunks().size());
        assertEquals(1, result.diagnostics().bm25CandidateCount());
        assertEquals(1, result.diagnostics().vectorCandidateCount());
    }

    private Chunk chunk(String id, UUID orgId, UUID kbId) {
        return new Chunk(id, orgId, kbId, UUID.randomUUID(), 0, id, List.of(), "test.md",
                null, null, null, "zh", "hash", Map.of());
    }
}
