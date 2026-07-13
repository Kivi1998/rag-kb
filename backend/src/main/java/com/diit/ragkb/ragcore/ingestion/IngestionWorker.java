package com.diit.ragkb.ragcore.ingestion;

import com.diit.ragkb.model.IngestionJob;
import com.diit.ragkb.ragcore.model.IngestionStatus;
import com.diit.ragkb.repository.IngestionJobRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.task.TaskExecutor;
import org.springframework.data.domain.PageRequest;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

/**
 * 轻量数据库任务表 Worker。多个实例可并行轮询，实际领取由条件更新保证一次只有一个实例成功。
 *
 * <p>在 T107 注入实际 Pipeline 前不会创建此 Bean，避免将尚未接入索引的文档错误标记 READY。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "rag.ingestion.worker", name = "enabled", havingValue = "true")
public class IngestionWorker {

    private final IngestionJobRepository jobRepository;
    private final IngestionJobLifecycleService lifecycleService;
    private final DocumentIngestionPipeline pipeline;
    private final IngestionMetrics metrics;
    @Qualifier("ingestionTaskExecutor")
    private final TaskExecutor ingestionTaskExecutor;
    @Qualifier("ingestionHeartbeatExecutor")
    private final ScheduledExecutorService heartbeatExecutor;
    @Value("${rag.ingestion.worker.id:${HOSTNAME:rag-ingestion-local}}")
    private String workerId;
    @Value("${rag.ingestion.worker.concurrency:4}")
    private int concurrency;
    @Value("${rag.ingestion.worker.batch-size:16}")
    private int batchSize;
    @Value("${rag.ingestion.worker.lease-duration-ms:1800000}")
    private long leaseDurationMs;

    @Scheduled(fixedDelayString = "${rag.ingestion.worker.poll-interval-ms:1000}")
    public void poll() {
        int recovered = lifecycleService.recoverExpiredLeases();
        if (recovered > 0) {
            log.warn("已恢复 {} 个过期摄取任务租约", recovered);
        }
        metrics.queueDepth(jobRepository.countByStatus(IngestionStatus.QUEUED));
        int available = concurrency - metrics.inFlight();
        if (available <= 0) {
            return;
        }
        int dispatchCount = Math.min(available, batchSize);
        jobRepository.findByStatusOrderByCreatedAtAsc(IngestionStatus.QUEUED, PageRequest.of(0, dispatchCount))
                .forEach(this::submit);
    }

    private void submit(IngestionJob candidate) {
        metrics.incrementInFlight();
        try {
            ingestionTaskExecutor.execute(() -> process(candidate));
        } catch (RejectedExecutionException ex) {
            metrics.decrementInFlight();
            log.debug("摄取线程池暂时没有空闲槽位，任务将在下一轮领取，jobId={}", candidate.getId());
        }
    }

    private void process(IngestionJob candidate) {
        try {
            lifecycleService.claim(candidate.getId(), workerId, Duration.ofMillis(leaseDurationMs)).ifPresent(task -> {
                ScheduledFuture<?> heartbeat;
                try {
                    heartbeat = startHeartbeat(task);
                } catch (RuntimeException ex) {
                    log.error("无法启动摄取任务心跳，任务转失败，jobId={}", task.jobId(), ex);
                    failIfStillOwned(task, ex);
                    return;
                }
                try {
                    pipeline.process(task);
                } catch (StaleIngestionLeaseException ex) {
                    log.warn("摄取任务租约已被接管，旧 Worker 停止写入，jobId={}, attempt={}, workerId={}",
                            task.jobId(), task.attempt(), task.leaseOwner());
                } catch (Exception ex) {
                    log.warn("摄取任务失败，jobId={}, documentId={}, attempt={}",
                            task.jobId(), task.documentId(), task.attempt(), ex);
                    failIfStillOwned(task, ex);
                } finally {
                    heartbeat.cancel(false);
                }
            });
        } finally {
            metrics.decrementInFlight();
        }
    }

    private void failIfStillOwned(IngestionTask task, Throwable cause) {
        try {
            lifecycleService.fail(task, cause);
        } catch (StaleIngestionLeaseException stale) {
            log.warn("任务失败时租约已被接管，不覆盖新 Worker 状态，jobId={}", task.jobId());
        }
    }

    private ScheduledFuture<?> startHeartbeat(IngestionTask task) {
        long intervalMs = Math.max(1_000, leaseDurationMs / 3);
        return heartbeatExecutor.scheduleAtFixedRate(() -> {
            try {
                if (!lifecycleService.heartbeat(task, Duration.ofMillis(leaseDurationMs))) {
                    log.warn("摄取任务续租失败，任务可能已被取消或接管，jobId={}", task.jobId());
                }
            } catch (RuntimeException ex) {
                log.warn("摄取任务心跳异常，将在下一周期重试，jobId={}", task.jobId(), ex);
            }
        }, intervalMs, intervalMs, TimeUnit.MILLISECONDS);
    }
}
