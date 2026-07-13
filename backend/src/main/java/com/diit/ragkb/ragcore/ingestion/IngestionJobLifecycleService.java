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
import java.time.Duration;
import java.util.List;
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
    private static final List<IngestionStatus> ACTIVE_STATUSES = List.of(
            IngestionStatus.PARSING, IngestionStatus.CHUNKING, IngestionStatus.EMBEDDING, IngestionStatus.INDEXING);

    private final IngestionJobRepository jobRepository;
    private final KnowledgeDocumentRepository documentRepository;

    /** 使用条件更新原子领取排队任务。 */
    @Transactional
    public Optional<IngestionTask> claim(UUID jobId) {
        return claim(jobId, "legacy-worker", Duration.ofMinutes(30));
    }

    /** 使用实例租约原子领取任务；租约过期后可由其他实例安全接管。 */
    @Transactional
    public Optional<IngestionTask> claim(UUID jobId, String workerId, Duration leaseDuration) {
        Instant now = Instant.now();
        Instant leaseExpiresAt = now.plus(leaseDuration);
        int updated = jobRepository.claimIfQueued(jobId, IngestionStatus.QUEUED, IngestionStatus.PARSING, now,
                workerId, leaseExpiresAt);
        if (updated == 0) {
            return Optional.empty();
        }
        IngestionJob job = jobRepository.findById(jobId)
                .orElseThrow(() -> new ResourceNotFoundException("摄取任务不存在"));
        KnowledgeDocument document = job.getDocument();
        updateDocumentStatus(document, IngestionStatus.PARSING);
        return Optional.of(new IngestionTask(job.getId(), document.getId(), job.getOrg().getId(),
                job.getKnowledgeBase().getId(), document.getName(), document.getContentType(),
                document.getObjectStoragePath(), document.getParseArtifactPath(), document.getParserVersion()));
    }

    /** 解析成功后记录可复用产物，后续向量化/索引失败重试不重复 OCR/ASR。 */
    @Transactional
    public void recordParsedArtifact(UUID jobId, String artifactPath, String parserName, String parserVersion) {
        KnowledgeDocument document = requireJob(jobId).getDocument();
        document.setParseArtifactPath(artifactPath);
        document.setParserName(parserName);
        document.setParserVersion(parserVersion);
        document.setParsedAt(Instant.now());
    }

    /** 活跃 Worker 定期续租；返回 false 表示任务已被删除、取消或接管。 */
    @Transactional
    public boolean heartbeat(UUID jobId, String workerId, Duration leaseDuration) {
        Instant now = Instant.now();
        return jobRepository.heartbeat(jobId, workerId, ACTIVE_STATUSES, now, now.plus(leaseDuration)) == 1;
    }

    /** 仅回收明确已过期的任务，超过最大尝试次数的任务转 FAILED，避免无限重试。 */
    @Transactional
    public int recoverExpiredLeases() {
        Instant now = Instant.now();
        int recovered = 0;
        for (IngestionJob job : jobRepository.findByStatusInAndLeaseExpiresAtBefore(ACTIVE_STATUSES, now)) {
            KnowledgeDocument document = job.getDocument();
            if (job.getAttempt() >= job.getMaxAttempts()) {
                String message = "摄取 Worker 租约过期，已达到最大尝试次数";
                if (jobRepository.failExpiredLease(job.getId(), ACTIVE_STATUSES, IngestionStatus.FAILED, message, now) == 1) {
                    document.setStatus(IngestionStatus.FAILED);
                    document.setLastError(message);
                    document.setLastErrorAt(now);
                    recovered++;
                }
            } else if (jobRepository.requeueExpiredLease(job.getId(), ACTIVE_STATUSES, IngestionStatus.QUEUED, now) == 1) {
                document.setStatus(IngestionStatus.QUEUED);
                recovered++;
            }
        }
        return recovered;
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
            clearLease(job);
        }
        updateDocumentStatus(job.getDocument(), nextStatus);
        return job;
    }

    /** 任意处理中阶段失败均进入 FAILED；已超最大尝试次数的任务即为死信状态。 */
    @Transactional
    public IngestionJob fail(UUID jobId, Throwable cause) {
        IngestionJob job = requireJob(jobId);
        // 删除请求具有更高优先级。Worker 已经拿到的旧快照不能把任务重新写回 FAILED。
        if (job.getStatus() == IngestionStatus.DELETING) {
            return job;
        }
        if (job.getStatus() != IngestionStatus.FAILED) {
            IngestionStateMachine.requireTransition(job.getStatus(), IngestionStatus.FAILED);
            job.setStatus(IngestionStatus.FAILED);
        }
        String message = safeErrorMessage(cause);
        job.setErrorMessage(message);
        job.setFinishedAt(Instant.now());
        clearLease(job);

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
        clearLease(job);

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

    private void clearLease(IngestionJob job) {
        job.setLeaseOwner(null);
        job.setLeaseExpiresAt(null);
        job.setLastHeartbeatAt(null);
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
