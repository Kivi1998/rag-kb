package com.diit.ragkb.ragcore.retrieval;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

class VectorRetrievalMetricsTest {

    @Test
    void recordsLatencyFallbackOverlapDifferenceAndOrphans() {
        SimpleMeterRegistry registry = new SimpleMeterRegistry();
        VectorRetrievalMetrics metrics = new VectorRetrievalMetrics(registry);

        long started = metrics.startNanos();
        metrics.recordLatency("milvus", started, true);
        metrics.recordFallback("milvus_to_elasticsearch");
        metrics.recordShadowComparison(
                List.of(new VectorHit("a", 1, 1), new VectorHit("b", 2, 0.9)),
                List.of(new VectorHit("b", 1, 1), new VectorHit("c", 2, 0.9)));
        metrics.recordOrphans(2);

        assertNotNull(registry.find("rag.vector.query.latency").tag("source", "milvus").timer());
        assertEquals(1, registry.find("rag.vector.fallback")
                .tag("path", "milvus_to_elasticsearch").counter().count());
        assertEquals(0.5, registry.find("rag.vector.shadow.topk.overlap_ratio").summary().max());
        assertEquals(2, registry.find("rag.vector.shadow.difference_count").summary().max());
        assertEquals(2, registry.find("rag.vector.orphan_hits").counter().count());
    }
}
