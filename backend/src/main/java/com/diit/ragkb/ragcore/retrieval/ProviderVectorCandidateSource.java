package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.config.VectorProvider;
import com.diit.ragkb.config.VectorProviderProperties;
import lombok.extern.slf4j.Slf4j;

import java.util.List;
import java.util.Objects;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executor;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;

/** 服务端固定的向量 Provider、影子读和回退链；调用方不能按请求覆盖模式。 */
@Slf4j
public class ProviderVectorCandidateSource implements VectorCandidateSource {

    private final VectorCandidateSource elasticsearch;
    private final VectorCandidateSource milvus;
    private final VectorProviderProperties properties;
    private final VectorRetrievalMetrics metrics;
    private final Executor shadowExecutor;

    public ProviderVectorCandidateSource(VectorCandidateSource elasticsearch, VectorCandidateSource milvus,
                                         VectorProviderProperties properties, VectorRetrievalMetrics metrics,
                                         Executor shadowExecutor) {
        this.elasticsearch = Objects.requireNonNull(elasticsearch, "ES 向量候选源不能为空");
        this.milvus = milvus;
        this.properties = Objects.requireNonNull(properties, "向量 Provider 配置不能为空");
        this.metrics = Objects.requireNonNull(metrics, "向量指标不能为空");
        this.shadowExecutor = Objects.requireNonNull(shadowExecutor, "影子查询执行器不能为空");
        if (properties.getProvider() != VectorProvider.ELASTICSEARCH && milvus == null) {
            throw new IllegalStateException("shadow/milvus 模式缺少 Milvus 向量候选源");
        }
    }

    @Override
    public List<VectorHit> search(VectorSearchRequest request) {
        return switch (properties.getProvider()) {
            case ELASTICSEARCH -> safeElasticsearch(request, "elasticsearch_to_bm25");
            case SHADOW -> shadow(request);
            case MILVUS -> primaryMilvus(request);
        };
    }

    private List<VectorHit> primaryMilvus(VectorSearchRequest request) {
        try {
            return timed("milvus", () -> milvus.search(request));
        } catch (RuntimeException milvusFailure) {
            if (!properties.isFallbackToElasticsearch()) throw milvusFailure;
            metrics.recordFallback("milvus_to_elasticsearch");
            log.warn("Milvus 向量检索失败，回退 ES kNN: {}", milvusFailure.getMessage());
            return safeElasticsearch(request, "milvus_and_elasticsearch_to_bm25");
        }
    }

    private List<VectorHit> shadow(VectorSearchRequest request) {
        List<VectorHit> online = safeElasticsearch(request, "elasticsearch_to_bm25");
        if (ThreadLocalRandom.current().nextDouble() < properties.getShadowSampleRate()) {
            CompletableFuture.supplyAsync(() -> timed("milvus_shadow", () -> milvus.search(request)), shadowExecutor)
                    .orTimeout(properties.getShadowTimeoutMs(), TimeUnit.MILLISECONDS)
                    .whenComplete((shadow, failure) -> {
                        if (failure == null) {
                            metrics.recordShadowComparison(online, shadow);
                        } else {
                            metrics.recordFallback("shadow_timeout_or_failure");
                            log.debug("Milvus 影子查询失败或超时: {}", failure.getMessage());
                        }
                    });
        }
        return online;
    }

    private List<VectorHit> safeElasticsearch(VectorSearchRequest request, String failurePath) {
        try {
            return timed("elasticsearch", () -> elasticsearch.search(request));
        } catch (RuntimeException failure) {
            metrics.recordFallback(failurePath);
            log.warn("ES kNN 不可用，退化为 BM25: {}", failure.getMessage());
            return List.of();
        }
    }

    private List<VectorHit> timed(String source, SearchOperation operation) {
        long started = metrics.startNanos();
        try {
            List<VectorHit> result = operation.search();
            metrics.recordLatency(source, started, true);
            return result == null ? List.of() : List.copyOf(result);
        } catch (RuntimeException exception) {
            metrics.recordLatency(source, started, false);
            throw exception;
        }
    }

    @FunctionalInterface
    private interface SearchOperation {
        List<VectorHit> search();
    }
}
