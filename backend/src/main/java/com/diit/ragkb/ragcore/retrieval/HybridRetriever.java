package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.ragcore.embedding.EmbeddingClient;
import com.diit.ragkb.ragcore.model.EmbeddingResult;
import com.diit.ragkb.ragcore.model.ModelClientException;
import com.diit.ragkb.ragcore.model.RetrievedChunk;
import com.diit.ragkb.ragcore.rerank.RerankerClient;
import com.diit.ragkb.ragcore.index.SearchRequest;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;

import java.util.List;
import java.util.HashMap;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/** 服务端注入租户边界的混合检索、可选重排与拒答决策。 */
@Slf4j
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

    private final HybridCandidateSource legacyCandidateSource;
    private final LexicalCandidateSource lexicalCandidateSource;
    private final VectorCandidateSource vectorCandidateSource;
    private final ChunkHydrator chunkHydrator;
    private final EmbeddingClient embeddingClient;
    private final ObjectProvider<RerankerClient> rerankerProvider;
    private final VectorRetrievalMetrics vectorMetrics;

    /** 新检索端口构造器；生产装配使用该入口。 */
    public HybridRetriever(LexicalCandidateSource lexicalCandidateSource,
                           VectorCandidateSource vectorCandidateSource,
                           ChunkHydrator chunkHydrator,
                           EmbeddingClient embeddingClient,
                           ObjectProvider<RerankerClient> rerankerProvider) {
        this(lexicalCandidateSource, vectorCandidateSource, chunkHydrator, embeddingClient, rerankerProvider, null);
    }

    /** 生产构造器，额外记录 Milvus 命中但 ES 正文缺失的孤儿向量。 */
    public HybridRetriever(LexicalCandidateSource lexicalCandidateSource,
                           VectorCandidateSource vectorCandidateSource,
                           ChunkHydrator chunkHydrator,
                           EmbeddingClient embeddingClient,
                           ObjectProvider<RerankerClient> rerankerProvider,
                           VectorRetrievalMetrics vectorMetrics) {
        this.legacyCandidateSource = null;
        this.lexicalCandidateSource = Objects.requireNonNull(lexicalCandidateSource, "词法候选源不能为空");
        this.vectorCandidateSource = Objects.requireNonNull(vectorCandidateSource, "向量候选源不能为空");
        this.chunkHydrator = Objects.requireNonNull(chunkHydrator, "Chunk 补齐器不能为空");
        this.embeddingClient = Objects.requireNonNull(embeddingClient, "EmbeddingClient 不能为空");
        this.rerankerProvider = Objects.requireNonNull(rerankerProvider, "RerankerProvider 不能为空");
        this.vectorMetrics = vectorMetrics;
    }

    /**
     * 评测脚本与存量测试的过渡构造器。新生产代码不得继续依赖数据库耦合的双路接口。
     */
    @Deprecated(forRemoval = false)
    public HybridRetriever(HybridCandidateSource candidateSource, EmbeddingClient embeddingClient,
                           ObjectProvider<RerankerClient> rerankerProvider) {
        this.legacyCandidateSource = Objects.requireNonNull(candidateSource, "候选源不能为空");
        this.lexicalCandidateSource = null;
        this.vectorCandidateSource = null;
        this.chunkHydrator = null;
        this.embeddingClient = Objects.requireNonNull(embeddingClient, "EmbeddingClient 不能为空");
        this.rerankerProvider = Objects.requireNonNull(rerankerProvider, "RerankerProvider 不能为空");
        this.vectorMetrics = null;
    }

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
        List<RetrievedChunk> bm25 = searchBm25(textRequest);

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
            vector = searchVector(new VectorSearchRequest(organizationId, knowledgeBaseId,
                    queryVector, options.candidateLimit(), options.documentIds()));
        } catch (ModelClientException ex) {
            // 向量模型短暂不可用时，保留关键词召回能力，避免整个检索入口不可用。
            log.warn("Embedding 不可用，降级为 BM25 结果: {}", ex.getMessage());
            vector = List.of();
            embeddingFallback = true;
        }
        List<RetrievedChunk> fused = RrfFusion.fuse(bm25, vector, options.bm25Weight(), options.vectorWeight());
        RetrievalDiagnostics diagnostics = new RetrievalDiagnostics(bm25.size(), vector.size(), fused.size(),
                embeddingFallback, false);
        // MIN_RRF_SCORE 校准时假定两路等权重（1.0/1.0）；查询意图分类会调低某一路的权重
        // （如语义型问题 bm25Weight=0.7），若直接对加权后的 fused.get(0) 判断，会把加权前
        // 本该通过阈值的单路命中（如排名 11 的 BM25-only 候选）误判为拒答。用未加权分数
        // 做这道早退检查，加权分数只用于候选排序/选择，两者互不影响。
        double unweightedTopScore = unweightedTopScore(bm25, vector);
        if (fused.isEmpty() || unweightedTopScore < MIN_RRF_SCORE) {
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
        if (reranked) {
            // 此前只检查排名第一的片段是否达标，排名靠后的低可信片段会原样进入生成 prompt 和引用来源，
            // 与其它高分片段混在一起可能干扰模型的多段融合判断。这里把同一阈值应用到每个候选片段；
            // 排名第一的分数最高，若它都过不了阈值，过滤后必然为空，走同一条拒答分支。
            selected = selected.stream()
                    .filter(candidate -> candidate.finalScore() == null || candidate.finalScore() >= MIN_RERANK_SCORE)
                    .toList();
            if (selected.isEmpty()) {
                return RetrievalResult.refuse("重排后最高相关性低于阈值，未在当前知识库中检索到足够依据", finalDiagnostics);
            }
        }
        return new RetrievalResult(selected, null, finalDiagnostics);
    }

    private List<RetrievedChunk> searchBm25(SearchRequest request) {
        return legacyCandidateSource != null
                ? legacyCandidateSource.searchBm25(request)
                : lexicalCandidateSource.search(request);
    }

    private List<RetrievedChunk> searchVector(VectorSearchRequest request) {
        if (legacyCandidateSource != null) return legacyCandidateSource.searchKnn(request);
        List<VectorHit> hits = vectorCandidateSource.search(request);
        if (hits.isEmpty()) return List.of();
        List<com.diit.ragkb.ragcore.model.Chunk> chunks = chunkHydrator.findByChunkIds(
                request.organizationId(), request.knowledgeBaseId(), hits.stream().map(VectorHit::chunkId).toList());
        Map<String, com.diit.ragkb.ragcore.model.Chunk> byId = new HashMap<>();
        chunks.forEach(chunk -> byId.put(chunk.id(), chunk));
        if (vectorMetrics != null) vectorMetrics.recordOrphans(hits.size() - byId.size());
        return hits.stream()
                .filter(hit -> byId.containsKey(hit.chunkId()))
                .map(hit -> new RetrievedChunk(byId.get(hit.chunkId()), null, hit.rank(), null, null, hit.score()))
                .toList();
    }

    /** {@code MIN_RRF_SCORE} 的早退检查专用：始终按等权重（1.0/1.0）计算，不受查询意图分类影响。 */
    private double unweightedTopScore(List<RetrievedChunk> bm25, List<RetrievedChunk> vector) {
        List<RetrievedChunk> unweighted = RrfFusion.fuse(bm25, vector);
        return unweighted.isEmpty() ? 0 : unweighted.get(0).rrfScore();
    }
}
