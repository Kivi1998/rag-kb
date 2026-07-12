package com.diit.ragkb.service;

import com.diit.ragkb.exception.AccessDeniedException;
import com.diit.ragkb.exception.ResourceNotFoundException;
import com.diit.ragkb.model.IngestionJob;
import com.diit.ragkb.model.KnowledgeBase;
import com.diit.ragkb.model.KnowledgeDocument;
import com.diit.ragkb.model.Member;
import com.diit.ragkb.model.MemberRole;
import com.diit.ragkb.ragcore.model.IngestionStatus;
import com.diit.ragkb.ragcore.ingestion.IngestionJobLifecycleService;
import com.diit.ragkb.ragcore.ingestion.DocumentDeletionService;
import com.diit.ragkb.ragcore.storage.ObjectStorage;
import com.diit.ragkb.ragcore.upload.UploadContentInspector;
import com.diit.ragkb.repository.IngestionJobRepository;
import com.diit.ragkb.repository.KnowledgeBaseRepository;
import com.diit.ragkb.repository.KnowledgeDocumentRepository;
import com.diit.ragkb.repository.MemberRepository;
import com.diit.ragkb.security.TenantContext;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.BufferedInputStream;
import java.security.DigestInputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.List;
import java.util.Locale;
import java.util.HexFormat;
import java.util.Set;
import java.util.UUID;

/**
 * 技术文档上传与摄取任务编排。
 *
 * <p>本服务只负责可靠地落原文件并创建 QUEUED 任务；解析、切分、向量化与索引由后续
 * Ingestion Worker 消费该任务。这样 HTTP 请求不会被复杂 PDF、代码仓库文档等长耗时工作阻塞。</p>
 */
@Service
@RequiredArgsConstructor
public class DocumentIngestionService {

    private static final int MAX_FILE_NAME_LENGTH = 500;
    private static final int CONTENT_SNIFF_BYTES = 8 * 1024;
    private static final Set<String> ALLOWED_EXTENSIONS = Set.of(
            "md", "markdown", "txt", "pdf", "docx", "pptx", "srt", "vtt", "json", "yaml", "yml", "xml",
            "java", "py", "js", "ts", "tsx", "jsx", "go", "rs", "sql", "sh", "bash",
            "properties", "conf", "ini", "gradle", "pom");

    private final KnowledgeBaseRepository kbRepository;
    private final KnowledgeDocumentRepository documentRepository;
    private final IngestionJobRepository jobRepository;
    private final MemberRepository memberRepository;
    private final ObjectStorage objectStorage;
    private final IngestionJobLifecycleService lifecycleService;
    private final DocumentDeletionService deletionService;

    /** 上传原文件并创建一个待消费的摄取任务。 */
    @Transactional
    public UploadResult upload(UUID kbId, MultipartFile file) {
        requireDocumentManager();
        KnowledgeBase kb = findKnowledgeBase(kbId);
        Member uploader = currentMember();
        UploadFile uploadFile = validate(file);

        KnowledgeDocument document = new KnowledgeDocument();
        document.setKnowledgeBase(kb);
        document.setOrg(kb.getOrg());
        document.setCreatedBy(uploader);
        document.setName(uploadFile.safeFileName());
        document.setSizeBytes(file.getSize());
        document.setStatus(IngestionStatus.QUEUED);
        // save 后由 Hibernate 生成 documentId；对象键不采用原文件名，避免路径注入和同名覆盖。
        document = documentRepository.save(document);

        String storageKey = buildStorageKey(kbId, document.getId(), uploadFile.extension());
        boolean stored = false;
        try (BufferedInputStream input = new BufferedInputStream(file.getInputStream())) {
            input.mark(CONTENT_SNIFF_BYTES);
            byte[] prefix = input.readNBytes(CONTENT_SNIFF_BYTES);
            input.reset();
            String detectedContentType = UploadContentInspector.inspect(uploadFile.safeFileName(), prefix);
            document.setContentType(detectedContentType);

            MessageDigest digest = sha256();
            try (DigestInputStream digestInput = new DigestInputStream(input, digest)) {
                objectStorage.put(storageKey, digestInput, file.getSize(), detectedContentType);
            }
            stored = true;
            document.setObjectStoragePath(storageKey);
            document.setContentSha256(HexFormat.of().formatHex(digest.digest()));

            IngestionJob job = new IngestionJob();
            job.setDocument(document);
            job.setKnowledgeBase(kb);
            job.setOrg(kb.getOrg());
            job.setStatus(IngestionStatus.QUEUED);
            job.setAttempt(0);
            job.setMaxAttempts(3);
            job = jobRepository.save(job);
            return new UploadResult(toDocumentView(document, job.getId()), toJobView(job));
        } catch (IllegalArgumentException ex) {
            cleanupStoredObject(stored, storageKey, ex);
            throw ex;
        } catch (IOException | RuntimeException ex) {
            cleanupStoredObject(stored, storageKey, ex);
            throw new IllegalStateException("文档对象存储失败，请稍后重试", ex);
        }
    }

    private void cleanupStoredObject(boolean stored, String storageKey, Exception original) {
            if (stored) {
                try {
                    objectStorage.delete(storageKey);
                } catch (IOException cleanupEx) {
                    original.addSuppressed(cleanupEx);
                }
            }
    }

    @Transactional(readOnly = true)
    public List<DocumentView> list(UUID kbId, IngestionStatus status) {
        findKnowledgeBase(kbId);
        return documentRepository.findByKnowledgeBaseIdAndOrgIdOrderByCreatedAtDesc(kbId, currentOrgId()).stream()
                .filter(document -> status == null || document.getStatus() == status)
                .map(document -> toDocumentView(document, latestJobId(document.getId())))
                .toList();
    }

    @Transactional(readOnly = true)
    public JobView getJob(UUID kbId, UUID jobId) {
        findKnowledgeBase(kbId);
        return toJobView(findJob(jobId, kbId));
    }

    /** 管理员可将失败任务重新放回队列；运行中或成功任务不能被重复入队。 */
    @Transactional
    public JobView retry(UUID kbId, UUID jobId) {
        requireDocumentManager();
        IngestionJob job = findJob(jobId, kbId);
        return toJobView(lifecycleService.retry(job.getId()));
    }

    /** 删除原文件、任务记录和文档元数据。向量索引删除将在 Worker 的删除补偿任务中接入。 */
    public void delete(UUID kbId, UUID documentId) {
        requireDocumentManager();
        findKnowledgeBase(kbId);
        KnowledgeDocument document = documentRepository.findByIdAndKnowledgeBaseIdAndOrgId(documentId, kbId, currentOrgId())
                .orElseThrow(() -> new ResourceNotFoundException("文档不存在"));
        deletionService.requestDeletion(document.getId());
        deletionService.cleanup(document.getId());
    }

    private IngestionJob findJob(UUID jobId, UUID kbId) {
        return jobRepository.findByIdAndKnowledgeBaseIdAndOrgId(jobId, kbId, currentOrgId())
                .orElseThrow(() -> new ResourceNotFoundException("摄取任务不存在"));
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
        if (orgId == null) {
            throw new IllegalStateException("缺少租户上下文");
        }
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

    private UploadFile validate(MultipartFile file) {
        if (file == null || file.isEmpty()) {
            throw new IllegalArgumentException("请选择非空文件");
        }
        String original = file.getOriginalFilename();
        if (original == null || original.isBlank()) {
            throw new IllegalArgumentException("文件名不能为空");
        }
        String safeFileName = original.replace('\\', '/');
        safeFileName = safeFileName.substring(safeFileName.lastIndexOf('/') + 1).trim();
        if (safeFileName.isBlank() || safeFileName.length() > MAX_FILE_NAME_LENGTH || safeFileName.contains("\u0000")) {
            throw new IllegalArgumentException("文件名不合法");
        }
        int dot = safeFileName.lastIndexOf('.');
        if (dot <= 0 || dot == safeFileName.length() - 1) {
            throw new IllegalArgumentException("文件必须带有受支持的扩展名");
        }
        String extension = safeFileName.substring(dot + 1).toLowerCase(Locale.ROOT);
        if (!ALLOWED_EXTENSIONS.contains(extension)) {
            throw new IllegalArgumentException("不支持的文件类型: " + extension);
        }
        return new UploadFile(safeFileName, extension);
    }

    private MessageDigest sha256() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("JRE 不支持 SHA-256", ex);
        }
    }

    private String buildStorageKey(UUID kbId, UUID documentId, String extension) {
        return "org/" + currentOrgId() + "/kb/" + kbId + "/documents/" + documentId + "." + extension;
    }

    private UUID latestJobId(UUID documentId) {
        return jobRepository.findFirstByDocumentIdOrderByCreatedAtDesc(documentId).map(IngestionJob::getId).orElse(null);
    }

    private DocumentView toDocumentView(KnowledgeDocument document, UUID jobId) {
        return new DocumentView(document.getId(), document.getKnowledgeBase().getId(), document.getName(),
                document.getSizeBytes(), document.getContentType(), document.getStatus(), document.getLastError(),
                document.getRetryCount(), document.getStatus() == IngestionStatus.FAILED && document.getRetryCount() < 3,
                document.getCreatedAt(), null, jobId);
    }

    private JobView toJobView(IngestionJob job) {
        return new JobView(job.getId(), job.getDocument().getId(), job.getKnowledgeBase().getId(), job.getStatus(),
                job.getErrorMessage(), job.getMaxAttempts(),
                job.getStatus() == IngestionStatus.FAILED && job.getAttempt() < job.getMaxAttempts(),
                job.getCreatedAt(), job.getUpdatedAt());
    }

    private record UploadFile(String safeFileName, String extension) { }

    public record UploadResult(DocumentView document, JobView job) { }

    public record DocumentView(UUID documentId, UUID kbId, String name, long size, String contentType,
                               IngestionStatus status, String errorMessage, int retryCount, boolean retryable,
                               Instant uploadedAt, Instant readyAt, UUID jobId) { }

    public record JobView(UUID jobId, UUID documentId, UUID kbId, IngestionStatus status, String errorMessage,
                          int retryLimit, boolean retryable, Instant createdAt, Instant updatedAt) { }
}
