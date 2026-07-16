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

    /**
     * Rerank 相关性分数拒答门槛，仅在 rerank 成功执行（非降级）时生效。
     *
     * <p>校准依据：2026-07-14 用 150 题人工标注评估集（eval-set-v2）+ bge-reranker-v2-m3
     * 做的分数分布分析（{@code eval/scripts/analyze_refusal_threshold.py}）。0.06 是该数据集上
     * 拒答 F1 最优点（F1=0.564，命中 11/25，仅误伤 3/125 可回答题）。</p>
     *
     * <p>已知局限（勿指望此门槛覆盖所有拒答场景）：rerank 分数衡量的是「主题相关性」而非
     * 「事实是否存在」，对 NO_RETRIEVAL 类（主题高度相关但具体数值/事实缺失，如"随机数种子设的
     * 多少"）与 SAFETY 类（内容确实可检索到，但因合规/安全原因应拒答，如汇总个人信息）几乎无
     * 区分力——这两类的分数与可正常回答的问题高度重叠，需要独立机制（事实核验、内容安全分类器）
     * 解决，不属于本次校准范围。</p>
     */
    private static final double MIN_RERANK_SCORE = 0.06;

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
        SearchRequest textRequest = new SearchRequest(organizationId, knowledgeBaseId, query, options.candidateLimit(),
                options.documentIds());
        List<RetrievedChunk> bm25 = candidateSource.searchBm25(textRequest);

        List<RetrievedChunk> vector;
        boolean embeddingFallback = false;
        try {
            List<Float> queryVector = options.precomputedQueryVector();
            if (queryVector == null) {
                EmbeddingResult embedding = embeddingClient.embed(List.of(query));
                if (embedding.vectors().size() != 1) {
                    throw new ModelClientException("查询 Embedding 返回数量不正确");
                }
                queryVector = embedding.vectors().get(0);
            }
            vector = candidateSource.searchKnn(new VectorSearchRequest(organizationId, knowledgeBaseId,
                    queryVector, options.candidateLimit(), options.documentIds()));
        } catch (ModelClientException ex) {
            // 向量模型短暂不可用时，保留关键词召回能力，避免整个检索入口不可用。
            log.warn("Embedding 不可用，降级为 BM25 结果: {}", ex.getMessage());
            vector = List.of();
            embeddingFallback = true;
        }
        List<RetrievedChunk> fused = RrfFusion.fuse(bm25, vector);
        RetrievalDiagnostics diagnostics = new RetrievalDiagnostics(bm25.size(), vector.size(), fused.size(),
                embeddingFallback, false);
        if (fused.isEmpty() || fused.get(0).rrfScore() < MIN_RRF_SCORE) {
            return RetrievalResult.refuse("未在当前知识库中检索到足够依据", diagnostics);
        }

        List<RetrievedChunk> selected = fused.stream().limit(options.resultLimit()).toList();
        RerankerClient reranker = rerankerProvider.getIfAvailable();
        boolean rerankFallback = false;
        boolean reranked = false;
        if (options.rerank() && reranker != null) {
            try {
                selected = reranker.rerank(query, fused, options.resultLimit());
                reranked = true;
            } catch (RuntimeException ex) {
                log.warn("Rerank 不可用，回退 RRF 结果: {}", ex.getMessage());
                rerankFallback = true;
            }
        }
        RetrievalDiagnostics finalDiagnostics = new RetrievalDiagnostics(bm25.size(), vector.size(), fused.size(),
                embeddingFallback, rerankFallback);
        if (selected.isEmpty()) {
            return RetrievalResult.refuse("未在当前知识库中检索到足够依据", finalDiagnostics);
        }
        if (reranked && selected.get(0).finalScore() != null && selected.get(0).finalScore() < MIN_RERANK_SCORE) {
            return RetrievalResult.refuse("重排后最高相关性低于阈值，未在当前知识库中检索到足够依据", finalDiagnostics);
        }
        return new RetrievalResult(selected, null, finalDiagnostics);
    }
}
