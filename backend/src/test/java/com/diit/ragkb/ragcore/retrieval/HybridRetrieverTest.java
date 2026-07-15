package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.ragcore.embedding.EmbeddingClient;
import com.diit.ragkb.ragcore.index.SearchRequest;
import com.diit.ragkb.ragcore.model.Chunk;
import com.diit.ragkb.ragcore.model.EmbeddingResult;
import com.diit.ragkb.ragcore.model.ModelClientException;
import com.diit.ragkb.ragcore.model.RetrievedChunk;
import com.diit.ragkb.ragcore.rerank.RerankerClient;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;

import java.util.List;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/** RRF 排序、Rerank 故障回退与空召回拒答回归。 */
class HybridRetrieverTest {

    @Test
    void rrfDeduplicatesAndRewardsCandidatesHitByBothChannels() {
        Chunk a = chunk("a");
        Chunk b = chunk("b");
        HybridCandidateSource source = new HybridCandidateSource() {
            @Override public List<RetrievedChunk> searchBm25(SearchRequest request) {
                return List.of(new RetrievedChunk(a, 1, null, null, null, 2.0),
                        new RetrievedChunk(b, 2, null, null, null, 1.5));
            }
            @Override public List<RetrievedChunk> searchKnn(VectorSearchRequest request) {
                return List.of(new RetrievedChunk(b, null, 1, null, null, 0.9));
            }
        };
        EmbeddingClient embedding = texts -> new EmbeddingResult("test", List.of(List.of(0.1f, 0.2f)));
        @SuppressWarnings("unchecked") ObjectProvider<RerankerClient> reranker = mock(ObjectProvider.class);
        when(reranker.getIfAvailable()).thenReturn(null);

        RetrievalResult result = new HybridRetriever(source, embedding, reranker)
                .retrieveWithDecision(UUID.randomUUID(), UUID.randomUUID(), "SearchService",
                        new RetrievalOptions(30, 2, true));

        assertTrue(!result.refused());
        assertEquals("b", result.chunks().get(0).chunk().id());
        assertEquals(2, result.chunks().get(0).bm25Rank());
        assertEquals(1, result.chunks().get(0).vectorRank());
        assertEquals(2, result.diagnostics().bm25CandidateCount());
        assertEquals(1, result.diagnostics().vectorCandidateCount());
    }

    @Test
    void rerankFailureFallsBackToRrf() {
        Chunk chunk = chunk("only");
        HybridCandidateSource source = new HybridCandidateSource() {
            @Override public List<RetrievedChunk> searchBm25(SearchRequest request) {
                return List.of(new RetrievedChunk(chunk, 1, null, null, null, 1.0));
            }
            @Override public List<RetrievedChunk> searchKnn(VectorSearchRequest request) { return List.of(); }
        };
        EmbeddingClient embedding = texts -> new EmbeddingResult("test", List.of(List.of(0.1f, 0.2f)));
        RerankerClient brokenReranker = (query, candidates, topK) -> { throw new IllegalStateException("timeout"); };
        @SuppressWarnings("unchecked") ObjectProvider<RerankerClient> reranker = mock(ObjectProvider.class);
        when(reranker.getIfAvailable()).thenReturn(brokenReranker);

        RetrievalResult result = new HybridRetriever(source, embedding, reranker)
                .retrieveWithDecision(UUID.randomUUID(), UUID.randomUUID(), "q", new RetrievalOptions(30, 1, true));
        assertTrue(!result.refused());
        assertEquals("only", result.chunks().get(0).chunk().id());
        assertTrue(result.diagnostics().rerankFallback());
    }

    @Test
    void embeddingFailureDegradesToBm25() {
        Chunk chunk = chunk("bm25-only");
        HybridCandidateSource source = new HybridCandidateSource() {
            @Override public List<RetrievedChunk> searchBm25(SearchRequest request) {
                return List.of(new RetrievedChunk(chunk, 1, null, null, null, 1.0));
            }
            @Override public List<RetrievedChunk> searchKnn(VectorSearchRequest request) {
                throw new AssertionError("Embedding 故障时不应执行 kNN 召回");
            }
        };
        EmbeddingClient embedding = texts -> { throw new ModelClientException("模型连接超时"); };
        @SuppressWarnings("unchecked") ObjectProvider<RerankerClient> reranker = mock(ObjectProvider.class);
        when(reranker.getIfAvailable()).thenReturn(null);

        RetrievalResult result = new HybridRetriever(source, embedding, reranker)
                .retrieveWithDecision(UUID.randomUUID(), UUID.randomUUID(), "SearchService",
                        new RetrievalOptions(30, 1, false));

        assertTrue(!result.refused());
        assertEquals("bm25-only", result.chunks().get(0).chunk().id());
        assertTrue(result.diagnostics().embeddingFallback());
    }

    @Test
    void emptyRecallIsRefused() {
        HybridCandidateSource source = new HybridCandidateSource() {
            @Override public List<RetrievedChunk> searchBm25(SearchRequest request) { return List.of(); }
            @Override public List<RetrievedChunk> searchKnn(VectorSearchRequest request) { return List.of(); }
        };
        EmbeddingClient embedding = texts -> new EmbeddingResult("test", List.of(List.of(0.1f, 0.2f)));
        @SuppressWarnings("unchecked") ObjectProvider<RerankerClient> reranker = mock(ObjectProvider.class);
        when(reranker.getIfAvailable()).thenReturn(null);

        RetrievalResult result = new HybridRetriever(source, embedding, reranker)
                .retrieveWithDecision(UUID.randomUUID(), UUID.randomUUID(), "不存在的内容",
                        new RetrievalOptions(30, 1, false));

        assertTrue(result.refused());
        assertEquals("未在当前知识库中检索到足够依据", result.refusalReason());
    }

    @Test
    void lowRerankScoreIsRefusedEvenWithRrfCandidates() {
        Chunk chunk = chunk("topically-close-but-irrelevant");
        HybridCandidateSource source = new HybridCandidateSource() {
            @Override public List<RetrievedChunk> searchBm25(SearchRequest request) {
                return List.of(new RetrievedChunk(chunk, 1, null, null, null, 1.0));
            }
            @Override public List<RetrievedChunk> searchKnn(VectorSearchRequest request) { return List.of(); }
        };
        EmbeddingClient embedding = texts -> new EmbeddingResult("test", List.of(List.of(0.1f, 0.2f)));
        RerankerClient lowScoreReranker = (query, candidates, topK) -> candidates.stream()
                .map(c -> new RetrievedChunk(c.chunk(), c.bm25Rank(), c.vectorRank(), c.rrfScore(), 0.02, 0.02))
                .toList();
        @SuppressWarnings("unchecked") ObjectProvider<RerankerClient> reranker = mock(ObjectProvider.class);
        when(reranker.getIfAvailable()).thenReturn(lowScoreReranker);

        RetrievalResult result = new HybridRetriever(source, embedding, reranker)
                .retrieveWithDecision(UUID.randomUUID(), UUID.randomUUID(), "q", new RetrievalOptions(30, 1, true));

        assertTrue(result.refused(), "rerank 分数低于阈值应拒答，即使 RRF 召回非空");
        assertEquals("重排后最高相关性低于阈值，未在当前知识库中检索到足够依据", result.refusalReason());
    }

    @Test
    void highRerankScorePassesThreshold() {
        Chunk chunk = chunk("genuinely-relevant");
        HybridCandidateSource source = new HybridCandidateSource() {
            @Override public List<RetrievedChunk> searchBm25(SearchRequest request) {
                return List.of(new RetrievedChunk(chunk, 1, null, null, null, 1.0));
            }
            @Override public List<RetrievedChunk> searchKnn(VectorSearchRequest request) { return List.of(); }
        };
        EmbeddingClient embedding = texts -> new EmbeddingResult("test", List.of(List.of(0.1f, 0.2f)));
        RerankerClient highScoreReranker = (query, candidates, topK) -> candidates.stream()
                .map(c -> new RetrievedChunk(c.chunk(), c.bm25Rank(), c.vectorRank(), c.rrfScore(), 0.95, 0.95))
                .toList();
        @SuppressWarnings("unchecked") ObjectProvider<RerankerClient> reranker = mock(ObjectProvider.class);
        when(reranker.getIfAvailable()).thenReturn(highScoreReranker);

        RetrievalResult result = new HybridRetriever(source, embedding, reranker)
                .retrieveWithDecision(UUID.randomUUID(), UUID.randomUUID(), "q", new RetrievalOptions(30, 1, true));

        assertTrue(!result.refused(), "rerank 分数高于阈值应正常返回结果");
        assertEquals("genuinely-relevant", result.chunks().get(0).chunk().id());
    }

    @Test
    void rerankFallbackSkipsRerankScoreGate() {
        Chunk chunk = chunk("only");
        HybridCandidateSource source = new HybridCandidateSource() {
            @Override public List<RetrievedChunk> searchBm25(SearchRequest request) {
                return List.of(new RetrievedChunk(chunk, 1, null, null, null, 1.0));
            }
            @Override public List<RetrievedChunk> searchKnn(VectorSearchRequest request) { return List.of(); }
        };
        EmbeddingClient embedding = texts -> new EmbeddingResult("test", List.of(List.of(0.1f, 0.2f)));
        RerankerClient brokenReranker = (query, candidates, topK) -> { throw new IllegalStateException("timeout"); };
        @SuppressWarnings("unchecked") ObjectProvider<RerankerClient> reranker = mock(ObjectProvider.class);
        when(reranker.getIfAvailable()).thenReturn(brokenReranker);

        RetrievalResult result = new HybridRetriever(source, embedding, reranker)
                .retrieveWithDecision(UUID.randomUUID(), UUID.randomUUID(), "q", new RetrievalOptions(30, 1, true));

        assertTrue(!result.refused(), "rerank 降级时不应套用 rerank 分数门槛（无分数可用）");
        assertTrue(result.diagnostics().rerankFallback());
    }

    @Test
    void emptyQuestionIsRefusedWithoutCallingModels() {
        HybridCandidateSource source = mock(HybridCandidateSource.class);
        EmbeddingClient embedding = mock(EmbeddingClient.class);
        @SuppressWarnings("unchecked") ObjectProvider<RerankerClient> reranker = mock(ObjectProvider.class);

        RetrievalResult result = new HybridRetriever(source, embedding, reranker)
                .retrieveWithDecision(UUID.randomUUID(), UUID.randomUUID(), " ", new RetrievalOptions(30, 1, false));

        assertTrue(result.refused());
        assertEquals("问题不能为空", result.refusalReason());
    }

    private Chunk chunk(String id) {
        UUID orgId = UUID.randomUUID();
        return new Chunk(id, orgId, UUID.randomUUID(), UUID.randomUUID(), 0, id, List.of(), "test", null,
                1, 1, "text", id, java.util.Map.of());
    }
}
