package com.diit.ragkb.ragcore.ingestion;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/** 摄取链路低基数指标，供 Prometheus 告警与容量规划使用。 */
@Component
public class IngestionMetrics {

    private final MeterRegistry registry;
    private final AtomicInteger inFlight = new AtomicInteger();
    private final AtomicLong queued = new AtomicLong();

    public IngestionMetrics(MeterRegistry registry) {
        this.registry = registry;
        registry.gauge("rag_ingestion_in_flight", inFlight);
        registry.gauge("rag_ingestion_queue_depth", queued);
    }

    public void uploadInitiated() {
        counter("rag_upload_sessions_total", "result", "initiated").increment();
    }

    public void uploadCompleted() {
        counter("rag_upload_sessions_total", "result", "completed").increment();
    }

    public void uploadExpired() {
        counter("rag_upload_sessions_total", "result", "expired").increment();
    }

    public int incrementInFlight() {
        return inFlight.incrementAndGet();
    }

    public int decrementInFlight() {
        return inFlight.decrementAndGet();
    }

    public int inFlight() {
        return inFlight.get();
    }

    public void queueDepth(long value) {
        queued.set(Math.max(0, value));
    }

    public long startNanos() {
        return System.nanoTime();
    }

    public void stageFinished(String stage, long startedNanos, boolean success) {
        Timer.builder("rag_ingestion_stage_duration")
                .description("RAG 摄取各阶段耗时")
                .tag("stage", stage)
                .tag("result", success ? "success" : "failure")
                .publishPercentileHistogram()
                .register(registry)
                .record(Duration.ofNanos(System.nanoTime() - startedNanos));
    }

    private Counter counter(String name, String tagName, String tagValue) {
        return Counter.builder(name).tag(tagName, tagValue).register(registry);
    }
}
