package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.ragcore.embedding.EmbeddingClient;
import com.diit.ragkb.ragcore.model.EmbeddingResult;
import com.diit.ragkb.ragcore.model.ModelClientException;
import com.diit.ragkb.ragcore.model.RetrievedChunk;
import com.diit.ragkb.ragcore.rerank.RerankerClient;
import com.diit.ragkb.ragcore.index.SearchRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;

import java.util.List;
import java.util.UUID;

/** 服务端注入租户边界的混合检索、可选重排与拒答决策。 */
@Slf4j
@RequiredArgsConstructor
public class HybridRetriever implements Retriever {

    private static final double MIN_RRF_SCORE = 0.01;

    private final HybridCandidateSource candidateSource;
    private final EmbeddingClient embeddingClient;
    private final ObjectProvider<RerankerClient> rerankerProvider;

    @Override
    public List<RetrievedChunk> retrieve(UUID organizationId, UUID knowledgeBaseId, String query, RetrievalOptions options) {
        return retrieveWithDecision(organizationId, knowledgeBaseId, query, options).chunks();
    }

    @Override
    public RetrievalResult retrieveWithDecision(UUID organizationId, UUID knowledgeBaseId, String query,
                                                RetrievalOptions options) {
        if (query == null || query.isBlank()) {
            return RetrievalResult.refuse("问题不能为空");
        }
        SearchRequest textRequest = new SearchRequest(organizationId, knowledgeBaseId, query, options.candidateLimit());
        List<RetrievedChunk> bm25 = candidateSource.searchBm25(textRequest);

        List<RetrievedChunk> vector;
        try {
            EmbeddingResult embedding = embeddingClient.embed(List.of(query));
            if (embedding.vectors().size() != 1) {
                throw new ModelClientException("查询 Embedding 返回数量不正确");
            }
            vector = candidateSource.searchKnn(new VectorSearchRequest(organizationId, knowledgeBaseId,
                    embedding.vectors().get(0), options.candidateLimit()));
        } catch (ModelClientException ex) {
            // 向量模型短暂不可用时，保留关键词召回能力，避免整个检索入口不可用。
            log.warn("Embedding 不可用，降级为 BM25 结果: {}", ex.getMessage());
            vector = List.of();
        }
        List<RetrievedChunk> fused = RrfFusion.fuse(bm25, vector);
        if (fused.isEmpty() || fused.get(0).rrfScore() < MIN_RRF_SCORE) {
            return RetrievalResult.refuse("未在当前知识库中检索到足够依据");
        }

        List<RetrievedChunk> selected = fused.stream().limit(options.resultLimit()).toList();
        RerankerClient reranker = rerankerProvider.getIfAvailable();
        if (options.rerank() && reranker != null) {
            try {
                selected = reranker.rerank(query, fused, options.resultLimit());
            } catch (RuntimeException ex) {
                log.warn("Rerank 不可用，回退 RRF 结果: {}", ex.getMessage());
            }
        }
        return selected.isEmpty() ? RetrievalResult.refuse("未在当前知识库中检索到足够依据")
                : new RetrievalResult(selected, null);
    }
}
