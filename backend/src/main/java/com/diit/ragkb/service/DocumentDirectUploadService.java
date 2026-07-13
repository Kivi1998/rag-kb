package com.diit.ragkb.service;

import com.diit.ragkb.exception.AccessDeniedException;
import com.diit.ragkb.exception.BusinessConflictException;
import com.diit.ragkb.exception.ResourceNotFoundException;
import com.diit.ragkb.model.*;
import com.diit.ragkb.ragcore.ingestion.IngestionMetrics;
import com.diit.ragkb.ragcore.model.IngestionStatus;
import com.diit.ragkb.ragcore.storage.ObjectStorage;
import com.diit.ragkb.ragcore.upload.DocumentUploadPolicy;
import com.diit.ragkb.ragcore.upload.UploadContentInspector;
import com.diit.ragkb.repository.*;
import com.diit.ragkb.security.TenantContext;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import java.io.BufferedInputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.security.DigestInputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.time.Instant;
import java.util.HexFormat;
import java.util.UUID;

/** MinIO/S3 预签名直传会话编排。 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DocumentDirectUploadService {

    private static final int CONTENT_SNIFF_BYTES = 8192;

    private final KnowledgeBaseRepository kbRepository;
    private final MemberRepository memberRepository;
    private final KnowledgeDocumentRepository documentRepository;
    private final IngestionJobRepository jobRepository;
    private final DocumentUploadSessionRepository sessionRepository;
    private final ObjectStorage objectStorage;
    private final DocumentUploadPolicy uploadPolicy;
    private final IngestionMetrics metrics;
    private final PlatformTransactionManager transactionManager;

    @Value("${rag.upload.direct.ttl-seconds:900}")
    private long ttlSeconds;

    @Value("${rag.upload.direct.verification-timeout-ms:900000}")
    private long verificationTimeoutMs;

    @Transactional
    public UploadSessionView initiate(UUID kbId, String fileName, long sizeBytes, String idempotencyKey) {
        requireDocumentManager();
        validateTtl();
        if (!objectStorage.supportsDirectUpload()) {
            throw new BusinessConflictException("当前对象存储未启用 MinIO/S3 预签名直传");
        }
        String normalizedKey = normalizeIdempotencyKey(idempotencyKey);
        UUID orgId = currentOrgId();
        KnowledgeBase kb = findKnowledgeBase(kbId);
        DocumentUploadPolicy.ValidatedUpload upload = uploadPolicy.validate(fileName, sizeBytes);

        var existing = sessionRepository.findByOrgIdAndKnowledgeBaseIdAndIdempotencyKey(orgId, kbId, normalizedKey);
        if (existing.isPresent()) {
            return existingView(existing.get());
        }

        Instant now = Instant.now();
        DocumentUploadSession session = new DocumentUploadSession();
        session.setId(UUID.randomUUID());
        session.setOrg(kb.getOrg());
        session.setKnowledgeBase(kb);
        session.setCreatedBy(currentMember());
        session.setFileName(upload.safeFileName());
        session.setContentType(upload.contentType());
        session.setExpectedSizeBytes(upload.sizeBytes());
        session.setIdempotencyKey(normalizedKey);
        session.setStatus(UploadSessionStatus.PENDING);
        session.setExpiresAt(now.plusSeconds(ttlSeconds));
        session.setObjectStoragePath(buildStagingKey(kbId, session.getId(), upload.extension()));
        sessionRepository.save(session);
        metrics.uploadInitiated();
        return withPresignedUrl(session);
    }

    public CompletedUploadView complete(UUID sessionId) {
        requireDocumentManager();
        UUID orgId = currentOrgId();
        validateVerificationTimeout();
        VerificationStart start = transaction().execute(status -> beginVerification(sessionId, orgId));
        if (start == null) {
            throw new IllegalStateException("无法创建上传校验事务");
        }
        if (start.completed() != null) {
            return start.completed();
        }

        VerifiedObject verified;
        try {
            verified = verifyUploadedObject(start.snapshot());
        } catch (RuntimeException ex) {
            resetVerification(start.snapshot(), ex);
            throw ex;
        }

        CompletedUploadView completed = transaction().execute(status -> finalizeVerification(start.snapshot(), verified));
        if (completed == null) {
            throw new IllegalStateException("无法提交上传校验事务");
        }
        return completed;
    }

    private VerificationStart beginVerification(UUID sessionId, UUID orgId) {
        DocumentUploadSession session = sessionRepository.findForUpdate(sessionId, orgId)
                .orElseThrow(() -> new ResourceNotFoundException("上传会话不存在"));
        if (session.getStatus() == UploadSessionStatus.COMPLETED) {
            return new VerificationStart(null, completedView(session));
        }
        if (session.getStatus() == UploadSessionStatus.VERIFYING) {
            throw new BusinessConflictException("上传对象正在校验，请稍后重试");
        }
        if (session.getStatus() != UploadSessionStatus.PENDING) {
            throw new BusinessConflictException("上传会话已失效");
        }
        if (!session.getExpiresAt().isAfter(Instant.now())) {
            throw new BusinessConflictException("上传会话已过期，请重新发起上传");
        }

        UUID token = UUID.randomUUID();
        session.setStatus(UploadSessionStatus.VERIFYING);
        session.setVerificationToken(token);
        session.setVerificationStartedAt(Instant.now());
        return new VerificationStart(new VerificationSnapshot(session.getId(), token, session.getFileName(),
                session.getObjectStoragePath(), session.getExpectedSizeBytes()), null);
    }

    private VerifiedObject verifyUploadedObject(VerificationSnapshot snapshot) {
        ObjectStorage.StoredObject object;
        try {
            object = objectStorage.stat(snapshot.objectStoragePath());
        } catch (IOException ex) {
            throw new BusinessConflictException("尚未检测到已上传对象，请完成 PUT 后重试");
        }
        if (object.sizeBytes() != snapshot.expectedSizeBytes()) {
            throw new BusinessConflictException("对象大小与上传会话声明不一致");
        }

        try (BufferedInputStream input = new BufferedInputStream(
                objectStorage.open(snapshot.objectStoragePath()))) {
            input.mark(CONTENT_SNIFF_BYTES);
            byte[] prefix = input.readNBytes(CONTENT_SNIFF_BYTES);
            input.reset();
            String detectedContentType = UploadContentInspector.inspect(snapshot.fileName(), prefix);

            MessageDigest digest = sha256();
            try (DigestInputStream digestInput = new DigestInputStream(input, digest)) {
                digestInput.transferTo(OutputStream.nullOutputStream());
            }
            return new VerifiedObject(detectedContentType, HexFormat.of().formatHex(digest.digest()), object.sizeBytes());
        } catch (IllegalArgumentException ex) {
            throw ex;
        } catch (IOException ex) {
            throw new IllegalStateException("校验直传对象失败，请稍后重试", ex);
        }
    }

    private CompletedUploadView finalizeVerification(VerificationSnapshot snapshot, VerifiedObject verifiedObject) {
        DocumentUploadSession session = sessionRepository.findForUpdate(snapshot.sessionId(), currentOrgId())
                .orElseThrow(() -> new ResourceNotFoundException("上传会话不存在"));
        if (session.getStatus() == UploadSessionStatus.COMPLETED) {
            return completedView(session);
        }
        requireVerificationToken(session, snapshot.verificationToken());

        KnowledgeDocument document = new KnowledgeDocument();
        document.setKnowledgeBase(session.getKnowledgeBase());
        document.setOrg(session.getOrg());
        document.setCreatedBy(session.getCreatedBy());
        document.setName(session.getFileName());
        document.setContentType(verifiedObject.contentType());
        document.setSizeBytes(verifiedObject.sizeBytes());
        document.setObjectStoragePath(session.getObjectStoragePath());
        document.setContentSha256(verifiedObject.sha256());
        document.setStatus(IngestionStatus.QUEUED);
        document = documentRepository.save(document);

        IngestionJob job = new IngestionJob();
        job.setDocument(document);
        job.setKnowledgeBase(session.getKnowledgeBase());
        job.setOrg(session.getOrg());
        job.setStatus(IngestionStatus.QUEUED);
        job.setAttempt(0);
        job.setMaxAttempts(3);
        job = jobRepository.save(job);

        session.setDocument(document);
        session.setStatus(UploadSessionStatus.COMPLETED);
        session.setCompletedAt(Instant.now());
        clearVerification(session);
        metrics.uploadCompleted();
        return new CompletedUploadView(session.getId(), document.getId(), job.getId(), IngestionStatus.QUEUED);
    }

    private void resetVerification(VerificationSnapshot snapshot, RuntimeException original) {
        try {
            transaction().executeWithoutResult(status -> {
                DocumentUploadSession session = sessionRepository.findForUpdate(snapshot.sessionId(), currentOrgId())
                        .orElse(null);
                if (session != null && session.getStatus() == UploadSessionStatus.VERIFYING
                        && snapshot.verificationToken().equals(session.getVerificationToken())) {
                    session.setStatus(UploadSessionStatus.PENDING);
                    clearVerification(session);
                }
            });
        } catch (RuntimeException resetError) {
            original.addSuppressed(resetError);
        }
    }

    private MessageDigest sha256() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("当前 JVM 不支持 SHA-256", ex);
        }
    }

    @Scheduled(fixedDelayString = "${rag.upload.direct.cleanup-interval-ms:60000}")
    public void cleanupExpiredSessions() {
        recoverStaleVerifications();
        while (true) {
            var candidates = sessionRepository.findExpiredSessionRefs(
                    UploadSessionStatus.PENDING, Instant.now(), PageRequest.of(0, 100));
            if (candidates.isEmpty()) return;
            int failures = 0;
            for (DocumentUploadSessionRepository.ExpiredSessionRef candidate : candidates) {
                try {
                    new TransactionTemplate(transactionManager).executeWithoutResult(ignored ->
                            cleanupExpiredSession(candidate.getSessionId(), candidate.getOrgId()));
                } catch (RuntimeException ex) {
                    failures++;
                    log.warn("清理过期上传会话失败，sessionId={}", candidate.getSessionId(), ex);
                }
            }
            // 若整批对象存储均不可用，等待下个调度周期，避免死循环打满数据库与日志。
            if (failures == candidates.size()) return;
        }
    }

    private void recoverStaleVerifications() {
        Instant cutoff = Instant.now().minusMillis(verificationTimeoutMs);
        while (true) {
            var candidates = sessionRepository.findStaleVerificationRefs(
                    UploadSessionStatus.VERIFYING, cutoff, PageRequest.of(0, 100));
            if (candidates.isEmpty()) return;
            for (DocumentUploadSessionRepository.ExpiredSessionRef candidate : candidates) {
                transaction().executeWithoutResult(ignored -> {
                    DocumentUploadSession session = sessionRepository.findForUpdate(
                            candidate.getSessionId(), candidate.getOrgId()).orElse(null);
                    if (session == null || session.getStatus() != UploadSessionStatus.VERIFYING
                            || session.getVerificationStartedAt() == null
                            || !session.getVerificationStartedAt().isBefore(cutoff)) return;
                    if (session.getExpiresAt().isAfter(Instant.now())) {
                        session.setStatus(UploadSessionStatus.PENDING);
                        clearVerification(session);
                    } else {
                        expireSession(session);
                    }
                });
            }
        }
    }

    public void cleanupExpiredSession(UUID sessionId, UUID orgId) {
        DocumentUploadSession session = sessionRepository.findForUpdate(sessionId, orgId).orElse(null);
        if (session == null || session.getStatus() != UploadSessionStatus.PENDING
                || session.getExpiresAt().isAfter(Instant.now())) return;
        expireSession(session);
    }

    private void expireSession(DocumentUploadSession session) {
        try {
            objectStorage.delete(session.getObjectStoragePath());
        } catch (IOException ex) {
            throw new IllegalStateException("清理过期上传对象失败", ex);
        }
        session.setStatus(UploadSessionStatus.EXPIRED);
        clearVerification(session);
        metrics.uploadExpired();
    }

    private UploadSessionView existingView(DocumentUploadSession session) {
        if (session.getStatus() == UploadSessionStatus.PENDING && session.getExpiresAt().isAfter(Instant.now())) {
            return withPresignedUrl(session);
        }
        if (session.getStatus() == UploadSessionStatus.VERIFYING) {
            return new UploadSessionView(session.getId(), session.getStatus(), null, null, null,
                    session.getExpiresAt(), null);
        }
        if (session.getStatus() == UploadSessionStatus.PENDING || session.getStatus() == UploadSessionStatus.EXPIRED) {
            throw new BusinessConflictException("该幂等键对应的上传会话已过期，请使用新的 Idempotency-Key");
        }
        return new UploadSessionView(session.getId(), session.getStatus(), null, null, null,
                session.getExpiresAt(), session.getDocument() == null ? null : session.getDocument().getId());
    }

    private UploadSessionView withPresignedUrl(DocumentUploadSession session) {
        Duration remaining = Duration.between(Instant.now(), session.getExpiresAt());
        if (remaining.isNegative() || remaining.isZero()) {
            return existingView(session);
        }
        try {
            ObjectStorage.PresignedUpload signed = objectStorage.presignPut(
                    session.getObjectStoragePath(), session.getContentType(), remaining);
            return new UploadSessionView(session.getId(), session.getStatus(), signed.url(), signed.method(),
                    signed.headers(), session.getExpiresAt(), null);
        } catch (IOException ex) {
            throw new IllegalStateException("生成预签名上传地址失败", ex);
        }
    }

    private CompletedUploadView completedView(DocumentUploadSession session) {
        KnowledgeDocument document = session.getDocument();
        UUID jobId = jobRepository.findFirstByDocumentIdOrderByCreatedAtDesc(document.getId())
                .orElseThrow(() -> new IllegalStateException("已完成上传会话缺少摄取任务")).getId();
        return new CompletedUploadView(session.getId(), document.getId(), jobId, document.getStatus());
    }

    private String buildStagingKey(UUID kbId, UUID sessionId, String extension) {
        return "org/" + currentOrgId() + "/kb/" + kbId + "/uploads/" + sessionId + "." + extension;
    }

    private String normalizeIdempotencyKey(String value) {
        if (value == null || value.isBlank() || value.length() > 200) {
            throw new IllegalArgumentException("Idempotency-Key 必须为 1-200 个字符");
        }
        return value.trim();
    }

    private void validateTtl() {
        // S3/MinIO V4 预签名 URL 的有效期上限为 7 天。
        if (ttlSeconds < 1 || ttlSeconds > 604_800) {
            throw new IllegalStateException("rag.upload.direct.ttl-seconds 必须在 1-604800 之间");
        }
    }

    private void validateVerificationTimeout() {
        if (verificationTimeoutMs < 1_000 || verificationTimeoutMs > 3_600_000) {
            throw new IllegalStateException("rag.upload.direct.verification-timeout-ms 必须在 1000-3600000 之间");
        }
    }

    private void requireVerificationToken(DocumentUploadSession session, UUID expectedToken) {
        if (session.getStatus() != UploadSessionStatus.VERIFYING
                || !expectedToken.equals(session.getVerificationToken())) {
            throw new BusinessConflictException("上传校验权已过期，请重试 complete");
        }
    }

    private void clearVerification(DocumentUploadSession session) {
        session.setVerificationToken(null);
        session.setVerificationStartedAt(null);
    }

    private TransactionTemplate transaction() {
        return new TransactionTemplate(transactionManager);
    }

    private KnowledgeBase findKnowledgeBase(UUID kbId) {
        return kbRepository.findByIdAndOrgId(kbId, currentOrgId())
                .orElseThrow(() -> new ResourceNotFoundException("知识库不存在"));
    }

    private Member currentMember() {
        return memberRepository.findByIdAndOrgId(TenantContext.getMemberId(), currentOrgId())
                .orElseThrow(() -> new ResourceNotFoundException("成员不存在"));
    }

    private UUID currentOrgId() {
        UUID orgId = TenantContext.getOrgId();
        if (orgId == null) throw new IllegalStateException("缺少租户上下文");
        return orgId;
    }

    private void requireDocumentManager() {
        MemberRole role;
        try {
            role = MemberRole.valueOf(TenantContext.getRole());
        } catch (RuntimeException ex) {
            throw new AccessDeniedException("当前成员没有文档管理权限");
        }
        if (role != MemberRole.OWNER && role != MemberRole.ADMIN) {
            throw new AccessDeniedException("仅组织 Owner 或 Admin 可以管理文档");
        }
    }

    public record UploadSessionView(UUID sessionId, UploadSessionStatus status, String uploadUrl, String method,
                                    java.util.Map<String, String> headers, Instant expiresAt, UUID documentId) { }

    public record CompletedUploadView(UUID sessionId, UUID documentId, UUID jobId, IngestionStatus status) { }

    private record VerificationSnapshot(UUID sessionId, UUID verificationToken, String fileName,
                                        String objectStoragePath, long expectedSizeBytes) { }

    private record VerificationStart(VerificationSnapshot snapshot, CompletedUploadView completed) { }

    private record VerifiedObject(String contentType, String sha256, long sizeBytes) { }
}
