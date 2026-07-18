package com.diit.ragkb.ragcore.retrieval;

import java.util.List;
import java.util.UUID;

/**
 * 混合检索与重排阶段的查询参数。
 *
 * <p>{@code documentIds} 非空时，BM25 与向量两路召回都会在租户过滤之外叠加一条
 * document_id 范围过滤，用于"先缩小范围再检索"（如只在用户选中的若干文档内搜索），
 * 既提精度又降延迟。目前仅提供检索层能力，尚无前端入口传入非空值。</p>
 *
 * <p>{@code precomputedQueryVector} 非空时，检索阶段直接复用这个向量，不再对 {@code query}
 * 重新调用 Embedding——用于记忆子系统已经在画像检索时算过同一句 resolvedQuestion 向量的场景，
 * 避免一次问答里对同一文本重复调用两次 Embedding。为空时行为不变，检索阶段自己调用 Embedding。</p>
 *
 * <p>{@code bm25Weight}/{@code vectorWeight} 是 RRF 融合时两路召回各自的权重，默认均为
 * {@code 1.0}（等价于原始未加权 RRF）。由查询意图分类结果驱动（见
 * {@code com.diit.ragkb.ragcore.intent}），例如精确检索型问题调高 {@code bm25Weight}。</p>
 */
public record RetrievalOptions(int candidateLimit, int resultLimit, boolean rerank, List<UUID> documentIds,
                               List<Float> precomputedQueryVector, double bm25Weight, double vectorWeight) {

    public RetrievalOptions {
        documentIds = documentIds == null ? List.of() : List.copyOf(documentIds);
        precomputedQueryVector = precomputedQueryVector == null ? null : List.copyOf(precomputedQueryVector);
        if (candidateLimit <= 0 || resultLimit <= 0 || resultLimit > candidateLimit) {
            throw new IllegalArgumentException("候选数必须大于等于结果数，且两者都大于 0");
        }
        if (bm25Weight < 0 || vectorWeight < 0) {
            throw new IllegalArgumentException("检索权重不能为负数");
        }
    }

    public RetrievalOptions(int candidateLimit, int resultLimit, boolean rerank, List<UUID> documentIds) {
        this(candidateLimit, resultLimit, rerank, documentIds, null, 1.0, 1.0);
    }

    public RetrievalOptions(int candidateLimit, int resultLimit, boolean rerank) {
        this(candidateLimit, resultLimit, rerank, List.of(), null, 1.0, 1.0);
    }

    public static RetrievalOptions defaults() {
        return new RetrievalOptions(50, 8, true, List.of(), null, 1.0, 1.0);
    }

    /** 附加一个已经算好的查询向量，供检索阶段复用，避免重复调用 Embedding。 */
    public RetrievalOptions withPrecomputedQueryVector(List<Float> vector) {
        return new RetrievalOptions(candidateLimit, resultLimit, rerank, documentIds, vector, bm25Weight, vectorWeight);
    }

    /** 按查询意图分类结果调整两路召回的 RRF 权重，不改变其他参数。 */
    public RetrievalOptions withWeights(double bm25Weight, double vectorWeight) {
        return new RetrievalOptions(candidateLimit, resultLimit, rerank, documentIds, precomputedQueryVector,
                bm25Weight, vectorWeight);
    }
}
