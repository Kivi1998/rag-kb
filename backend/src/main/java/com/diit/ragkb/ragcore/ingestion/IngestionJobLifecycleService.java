package com.diit.ragkb.ragcore.ingestion;

import com.diit.ragkb.exception.ResourceNotFoundException;
import com.diit.ragkb.model.IngestionJob;
import com.diit.ragkb.model.KnowledgeDocument;
import com.diit.ragkb.ragcore.model.IngestionStateMachine;
import com.diit.ragkb.ragcore.model.IngestionStatus;
import com.diit.ragkb.repository.IngestionJobRepository;
import com.diit.ragkb.repository.KnowledgeDocumentRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

/**
 * 摄取任务状态机的唯一写入口。
 *
 * <p>HTTP 层只能请求重试，后台 Worker 只能通过此类领取和推进任务；所有状态变化同时更新
 * ingestion_job 与 document，避免列表页与任务详情出现不一致。</p>
 */
@Service
@RequiredArgsConstructor
public class IngestionJobLifecycleService {

    private static final int MAX_ERROR_MESSAGE_LENGTH = 4_000;

    private final IngestionJobRepository jobRepository;
    private final KnowledgeDocumentRepository documentRepository;

    /** 使用条件更新原子领取排队任务。 */
    @Transactional
    public Optional<IngestionJob> claim(UUID jobId) {
        Instant now = Instant.now();
        int updated = jobRepository.claimIfQueued(jobId, IngestionStatus.QUEUED, IngestionStatus.PARSING, now);
        if (updated == 0) {
            return Optional.empty();
        }
        IngestionJob job = jobRepository.findById(jobId)
                .orElseThrow(() -> new ResourceNotFoundException("摄取任务不存在"));
        updateDocumentStatus(job.getDocument(), IngestionStatus.PARSING);
        return Optional.of(job);
    }

    /** Worker 在一个合法阶段完成后推进至下一阶段。 */
    @Transactional
    public IngestionJob advance(UUID jobId, IngestionStatus nextStatus) {
        IngestionJob job = requireJob(jobId);
        IngestionStateMachine.requireTransition(job.getStatus(), nextStatus);
        job.setStatus(nextStatus);
        if (nextStatus == IngestionStatus.READY) {
            job.setFinishedAt(Instant.now());
            job.setErrorMessage(null);
        }
        updateDocumentStatus(job.getDocument(), nextStatus);
        return job;
    }

    /** 任意处理中阶段失败均进入 FAILED；已超最大尝试次数的任务即为死信状态。 */
    @Transactional
    public IngestionJob fail(UUID jobId, Throwable cause) {
        IngestionJob job = requireJob(jobId);
        if (job.getStatus() != IngestionStatus.FAILED) {
            IngestionStateMachine.requireTransition(job.getStatus(), IngestionStatus.FAILED);
            job.setStatus(IngestionStatus.FAILED);
        }
        String message = safeErrorMessage(cause);
        job.setErrorMessage(message);
        job.setFinishedAt(Instant.now());

        KnowledgeDocument document = job.getDocument();
        document.setStatus(IngestionStatus.FAILED);
        document.setLastError(message);
        document.setLastErrorAt(Instant.now());
        return job;
    }

    /** 管理员触发的失败任务重试；尝试次数由下一次原子领取时递增。 */
    @Transactional
    public IngestionJob retry(UUID jobId) {
        IngestionJob job = requireJob(jobId);
        if (job.getStatus() != IngestionStatus.FAILED) {
            throw new IllegalArgumentException("仅失败的摄取任务可以重试");
        }
        if (job.getAttempt() >= job.getMaxAttempts()) {
            throw new IllegalArgumentException("摄取任务已达到最大重试次数");
        }
        IngestionStateMachine.requireTransition(IngestionStatus.FAILED, IngestionStatus.QUEUED);
        job.setStatus(IngestionStatus.QUEUED);
        job.setErrorMessage(null);
        job.setStartedAt(null);
        job.setFinishedAt(null);

        KnowledgeDocument document = job.getDocument();
        document.setStatus(IngestionStatus.QUEUED);
        document.setRetryCount(document.getRetryCount() + 1);
        document.setLastError(null);
        document.setLastErrorAt(null);
        return job;
    }

    private IngestionJob requireJob(UUID jobId) {
        return jobRepository.findById(jobId)
                .orElseThrow(() -> new ResourceNotFoundException("摄取任务不存在"));
    }

    private void updateDocumentStatus(KnowledgeDocument document, IngestionStatus status) {
        document.setStatus(status);
    }

    private String safeErrorMessage(Throwable cause) {
        String message = cause == null ? "摄取任务失败" : cause.getMessage();
        if (message == null || message.isBlank()) {
            message = cause == null ? "摄取任务失败" : cause.getClass().getSimpleName();
        }
        return message.length() <= MAX_ERROR_MESSAGE_LENGTH
                ? message : message.substring(0, MAX_ERROR_MESSAGE_LENGTH);
    }
}
