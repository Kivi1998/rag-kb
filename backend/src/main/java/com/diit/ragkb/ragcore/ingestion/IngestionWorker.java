package com.diit.ragkb.ragcore.ingestion;

import com.diit.ragkb.model.IngestionJob;
import com.diit.ragkb.ragcore.model.IngestionStatus;
import com.diit.ragkb.repository.IngestionJobRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

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

    @Scheduled(fixedDelayString = "${rag.ingestion.worker.poll-interval-ms:1000}")
    public void poll() {
        int batchSize = 10;
        jobRepository.findByStatusOrderByCreatedAtAsc(IngestionStatus.QUEUED).stream()
                .limit(batchSize)
                .forEach(this::process);
    }

    private void process(IngestionJob candidate) {
        lifecycleService.claim(candidate.getId()).ifPresent(task -> {
            try {
                pipeline.process(task);
            } catch (Exception ex) {
                log.warn("摄取任务失败，jobId={}, documentId={}, attempt={}",
                        task.jobId(), task.documentId(), candidate.getAttempt() + 1, ex);
                lifecycleService.fail(task.jobId(), ex);
            }
        });
    }
}
