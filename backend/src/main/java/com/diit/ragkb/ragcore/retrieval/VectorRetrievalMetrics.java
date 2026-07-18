package com.diit.ragkb.ragcore.retrieval;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.DistributionSummary;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;

import java.time.Duration;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** ES/Milvus 切流期间的低基数可观测指标。 */
public class VectorRetrievalMetrics {

    private final MeterRegistry registry;

    public VectorRetrievalMetrics(MeterRegistry registry) {
        this.registry = registry;
    }

    public long startNanos() {
        return System.nanoTime();
    }

    public void recordLatency(String source, long startedNanos, boolean success) {
        Timer.builder("rag.vector.query.latency")
                .tag("source", source)
                .tag("outcome", success ? "success" : "failure")
                .register(registry)
                .record(Duration.ofNanos(Math.max(0, System.nanoTime() - startedNanos)));
    }

    public void recordFallback(String path) {
        Counter.builder("rag.vector.fallback")
                .tag("path", path).register(registry).increment();
    }

    public void recordShadowComparison(List<VectorHit> online, List<VectorHit> shadow) {
        Set<String> onlineIds = ids(online);
        Set<String> shadowIds = ids(shadow);
        int denominator = Math.max(1, Math.min(onlineIds.size(), shadowIds.size()));
        Set<String> overlap = new HashSet<>(onlineIds);
        overlap.retainAll(shadowIds);
        DistributionSummary.builder("rag.vector.shadow.topk.overlap_ratio")
                .register(registry).record((double) overlap.size() / denominator);
        Set<String> difference = new HashSet<>(onlineIds);
        difference.addAll(shadowIds);
        Set<String> common = new HashSet<>(onlineIds);
        common.retainAll(shadowIds);
        difference.removeAll(common);
        DistributionSummary.builder("rag.vector.shadow.difference_count")
                .register(registry).record(difference.size());
    }

    public void recordOrphans(int count) {
        if (count <= 0) return;
        Counter.builder("rag.vector.orphan_hits").register(registry).increment(count);
    }

    private Set<String> ids(List<VectorHit> hits) {
        Set<String> result = new HashSet<>();
        if (hits != null) hits.forEach(hit -> result.add(hit.chunkId()));
        return result;
    }
}
