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

    @Transactional
    public CompletedUploadView complete(UUID sessionId) {
        requireDocumentManager();
        DocumentUploadSession session = sessionRepository.findForUpdate(sessionId, currentOrgId())
                .orElseThrow(() -> new ResourceNotFoundException("上传会话不存在"));
        if (session.getStatus() == UploadSessionStatus.COMPLETED) {
            return completedView(session);
        }
        if (session.getStatus() != UploadSessionStatus.PENDING) {
            throw new BusinessConflictException("上传会话已失效");
        }
        if (!session.getExpiresAt().isAfter(Instant.now())) {
            expireSession(session);
            throw new BusinessConflictException("上传会话已过期，请重新发起上传");
        }

        ObjectStorage.StoredObject object;
        try {
            object = objectStorage.stat(session.getObjectStoragePath());
        } catch (IOException ex) {
            throw new BusinessConflictException("尚未检测到已上传对象，请完成 PUT 后重试");
        }
        if (object.sizeBytes() != session.getExpectedSizeBytes()) {
            throw new BusinessConflictException("对象大小与上传会话声明不一致");
        }

        VerifiedObject verifiedObject = verifyUploadedObject(session);

        KnowledgeDocument document = new KnowledgeDocument();
        document.setKnowledgeBase(session.getKnowledgeBase());
        document.setOrg(session.getOrg());
        document.setCreatedBy(session.getCreatedBy());
        document.setName(session.getFileName());
        document.setContentType(verifiedObject.contentType());
        document.setSizeBytes(object.sizeBytes());
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
        metrics.uploadCompleted();
        return new CompletedUploadView(session.getId(), document.getId(), job.getId(), IngestionStatus.QUEUED);
    }

    /**
     * 直传完成后由服务端重新读取对象：文件魔数防止扩展名伪装，SHA-256 用于后续去重和完整性追踪。
     * 该校验在会话行锁内执行，避免并发 complete 创建重复文档。
     */
    private VerifiedObject verifyUploadedObject(DocumentUploadSession session) {
        try (BufferedInputStream input = new BufferedInputStream(
                objectStorage.open(session.getObjectStoragePath()))) {
            input.mark(CONTENT_SNIFF_BYTES);
            byte[] prefix = input.readNBytes(CONTENT_SNIFF_BYTES);
            input.reset();
            String detectedContentType = UploadContentInspector.inspect(session.getFileName(), prefix);

            MessageDigest digest = sha256();
            try (DigestInputStream digestInput = new DigestInputStream(input, digest)) {
                digestInput.transferTo(OutputStream.nullOutputStream());
            }
            return new VerifiedObject(detectedContentType, HexFormat.of().formatHex(digest.digest()));
        } catch (IllegalArgumentException ex) {
            throw ex;
        } catch (IOException ex) {
            throw new IllegalStateException("校验直传对象失败，请稍后重试", ex);
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
        metrics.uploadExpired();
    }

    private UploadSessionView existingView(DocumentUploadSession session) {
        if (session.getStatus() == UploadSessionStatus.PENDING && session.getExpiresAt().isAfter(Instant.now())) {
            return withPresignedUrl(session);
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

    private record VerifiedObject(String contentType, String sha256) { }
}
