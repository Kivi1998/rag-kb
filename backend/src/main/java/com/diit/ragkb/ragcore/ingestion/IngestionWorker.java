package com.diit.ragkb.ragcore.ingestion;

import com.diit.ragkb.model.IngestionJob;
import com.diit.ragkb.ragcore.model.IngestionStatus;
import com.diit.ragkb.repository.IngestionJobRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.task.TaskExecutor;
import org.springframework.data.domain.PageRequest;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 轻量数据库任务表 Worker。多个实例可并行轮询，实际领取由条件更新保证一次只有一个实例成功。
 *
 * <p>在 T107 注入实际 Pipeline 前不会创建此 Bean，避免将尚未接入索引的文档错误标记 READY。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
@ConditionalOnBean(DocumentIngestionPipeline.class)
@ConditionalOnProperty(prefix = "rag.ingestion.worker", name = "enabled", havingValue = "true")
public class IngestionWorker {

    private final IngestionJobRepository jobRepository;
    private final IngestionJobLifecycleService lifecycleService;
    private final DocumentIngestionPipeline pipeline;
    @Qualifier("ingestionTaskExecutor")
    private final TaskExecutor ingestionTaskExecutor;
    @Value("${rag.ingestion.worker.id:${HOSTNAME:rag-ingestion-local}}")
    private String workerId;
    @Value("${rag.ingestion.worker.concurrency:4}")
    private int concurrency;
    @Value("${rag.ingestion.worker.batch-size:16}")
    private int batchSize;
    @Value("${rag.ingestion.worker.lease-duration-ms:1800000}")
    private long leaseDurationMs;

    private final AtomicInteger inFlight = new AtomicInteger();

    @Scheduled(fixedDelayString = "${rag.ingestion.worker.poll-interval-ms:1000}")
    public void poll() {
        int recovered = lifecycleService.recoverExpiredLeases();
        if (recovered > 0) {
            log.warn("已恢复 {} 个过期摄取任务租约", recovered);
        }
        int available = concurrency - inFlight.get();
        if (available <= 0) {
            return;
        }
        int dispatchCount = Math.min(available, batchSize);
        jobRepository.findByStatusOrderByCreatedAtAsc(IngestionStatus.QUEUED, PageRequest.of(0, dispatchCount))
                .forEach(this::submit);
    }

    private void submit(IngestionJob candidate) {
        inFlight.incrementAndGet();
        try {
            ingestionTaskExecutor.execute(() -> process(candidate));
        } catch (RejectedExecutionException ex) {
            inFlight.decrementAndGet();
            log.debug("摄取线程池暂时没有空闲槽位，任务将在下一轮领取，jobId={}", candidate.getId());
        }
    }

    private void process(IngestionJob candidate) {
        try {
            lifecycleService.claim(candidate.getId(), workerId, Duration.ofMillis(leaseDurationMs)).ifPresent(task -> {
            try {
                pipeline.process(task);
            } catch (Exception ex) {
                log.warn("摄取任务失败，jobId={}, documentId={}, attempt={}",
                        task.jobId(), task.documentId(), candidate.getAttempt() + 1, ex);
                lifecycleService.fail(task.jobId(), ex);
            }
            });
        } finally {
            inFlight.decrementAndGet();
        }
    }
}
