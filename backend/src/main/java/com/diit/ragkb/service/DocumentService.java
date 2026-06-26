package com.diit.ragkb.service;

import com.diit.ragkb.exception.AccessDeniedException;
import com.diit.ragkb.exception.ResourceNotFoundException;
import com.diit.ragkb.model.*;
import com.diit.ragkb.repository.DocumentRepository;
import com.diit.ragkb.repository.KnowledgeBaseRepository;
import com.diit.ragkb.repository.MemberRepository;
import com.diit.ragkb.repository.OrganizationRepository;
import com.diit.ragkb.security.TenantContext;
import com.diit.ragkb.service.ragflow.RagFlowClient;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.Set;
import java.util.UUID;

/**
 * 文档服务
 *
 * 上传:校验 KB 归属 → 校验文件类型/大小 → 持久化 → 推送 RAGFlow → 触发解析
 * 列表:只返回存储状态,不触发 RAGFlow 查询
 * 详情:查时刷新——PARSING 状态实时查 RAGFlow
 * 删除:先删 RAGFlow → 再删 DB;需 admin/owner 权限
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DocumentService {

    private final DocumentRepository documentRepository;
    private final KnowledgeBaseRepository kbRepository;
    private final OrganizationRepository orgRepository;
    private final MemberRepository memberRepository;
    private final RagFlowClient ragFlowClient;
    private final KnowledgeBaseService knowledgeBaseService;
    private final PlatformTransactionManager transactionManager;

    /** 允许的文件扩展名白名单 */
    private static final Set<String> ALLOWED_EXTENSIONS = Set.of(
            "pdf", "docx", "doc", "txt", "md", "pptx", "xlsx"
    );

    /** 文件大小上限:50MB */
    private static final long MAX_FILE_SIZE = 50L * 1024 * 1024;

    /**
     * 上传文档
     * 1. 校验 KB 归属(跨租户 → 404)
     * 2. 校验文件类型(扩展名为主 + MIME 辅助)和大小(≤50MB)
     * 3. 持久化文档记录(状态=UPLOADING)
     * 4. 流式推送 RAGFlow
     * 5. 触发 RAGFlow 解析
     * 6. 成功后翻状态=PARSING;任一步失败置 FAILED
     */
    @Transactional
    public Document upload(UUID kbId, UUID orgId, UUID uploaderId, MultipartFile file) {
        // 1. 校验 KB 归属
        KnowledgeBase kb = knowledgeBaseService.getByIdAndCurrentOrg(kbId);

        // 2. 校验文件类型
        String originalFilename = file.getOriginalFilename();
        if (originalFilename == null || originalFilename.isBlank()) {
            throw new IllegalArgumentException("文件名不能为空");
        }
        String extension = getExtension(originalFilename).toLowerCase();
        if (!ALLOWED_EXTENSIONS.contains(extension)) {
            throw new IllegalArgumentException("不支持的文件类型: ." + extension +
                    ",允许类型: " + String.join(",", ALLOWED_EXTENSIONS));
        }

        // MIME 辅助校验(不强制,因客户端 Content-Type 常为 octet-stream)
        String contentType = file.getContentType();

        // 3. 校验文件大小
        if (file.getSize() > MAX_FILE_SIZE) {
            throw new IllegalArgumentException("文件大小超过限制(最大 50MB)");
        }

        // 4. 持久化文档记录
        Organization org = orgRepository.findById(orgId)
                .orElseThrow(() -> new ResourceNotFoundException("组织不存在"));
        Member creator = memberRepository.findById(uploaderId)
                .orElseThrow(() -> new ResourceNotFoundException("成员不存在"));

        Document doc = new Document();
        doc.setKb(kb);
        doc.setOrg(org);
        doc.setName(originalFilename);
        doc.setContentType(contentType);
        doc.setSizeBytes(file.getSize());
        doc.setStatus(DocumentStatus.UPLOADING);
        doc.setCreatedBy(creator);
        doc = documentRepository.save(doc);

        // 5. 推送 RAGFlow + 触发解析(外层事务,失败时用 REQUIRES_NEW 保存 FAILED 状态)
        UUID docId = doc.getId();
        try {
            String ragflowDocId = ragFlowClient.uploadDocument(
                    kb.getRagflowDatasetId(),
                    originalFilename,
                    file.getResource(),
                    contentType
            );
            doc.setRagflowDocId(ragflowDocId);

            // 触发解析
            ragFlowClient.parseDocument(kb.getRagflowDatasetId(), ragflowDocId);

            // 6. 成功 → 状态翻 PARSING
            doc.setStatus(DocumentStatus.PARSING);
            doc = documentRepository.save(doc);
            log.info("文档上传成功,kbId={},docId={},ragflowDocId={}", kbId, docId, ragflowDocId);
        } catch (Exception e) {
            // 用 REQUIRES_NEW 独立事务保存 FAILED 状态(外层事务会回滚)
            log.error("文档上传失败,kbId={},docId={}: {}", kbId, docId, e.getMessage());
            saveFailedStatus(docId, e.getMessage());
            throw new RuntimeException("文档上传失败: " + e.getMessage(), e);
        }

        return doc;
    }

    /**
     * 列出知识库下文档
     * 先校验 KB 归属(跨租户 → 404)
     * 列表只返回存储状态,不对 PARSING 文档触发 RAGFlow 查询
     */
    @Transactional(readOnly = true)
    public List<Document> listByKb(UUID kbId, UUID orgId) {
        // 校验 KB 归属
        knowledgeBaseService.getByIdAndCurrentOrg(kbId);
        return documentRepository.findByKbIdAndOrgId(kbId, orgId);
    }

    /**
     * 查询单文档详情
     * 查时刷新策略:若状态=PARSING 则调 RAGFlow 更新状态;终态直接返回
     */
    @Transactional
    public Document getById(UUID docId, UUID kbId, UUID orgId) {
        Document doc = documentRepository.findByIdAndKbIdAndOrgId(docId, kbId, orgId)
                .orElseThrow(() -> new ResourceNotFoundException("文档不存在"));

        // 查时刷新:PARSING 状态实时查 RAGFlow
        if (doc.getStatus() == DocumentStatus.PARSING && doc.getRagflowDocId() != null) {
            try {
                String ragflowStatus = ragFlowClient.getDocumentStatus(
                        doc.getKb().getRagflowDatasetId(), doc.getRagflowDocId());
                // RAGFlow 状态映射:run="3"表示解析完成,run="4"表示解析失败
                if ("3".equals(ragflowStatus)) {
                    doc.setStatus(DocumentStatus.READY);
                    documentRepository.save(doc);
                    log.info("文档状态更新:PARSING→READY,docId={}", docId);
                } else if ("4".equals(ragflowStatus)) {
                    doc.setStatus(DocumentStatus.FAILED);
                    doc.setErrorMessage("RAGFlow 解析失败");
                    documentRepository.save(doc);
                    log.info("文档状态更新:PARSING→FAILED,docId={}", docId);
                }
                // 其他状态保持 PARSING
            } catch (Exception e) {
                log.warn("查询 RAGFlow 状态异常(保持 PARSING),docId={}: {}", docId, e.getMessage());
            }
        }

        return doc;
    }

    /**
     * 删除文档
     * 先校验 KB 归属(跨租户 → 404)
     * 校验权限:owner/admin(member → 403)
     * 先删 RAGFlow → 再删 DB;RAGFlow 失败时置状态 FAILED 并保留记录
     */
    @Transactional
    public void delete(UUID docId, UUID kbId, UUID orgId, String callerRole) {
        // 校验 KB 归属(绑定 kbId + orgId)
        Document doc = documentRepository.findByIdAndKbIdAndOrgId(docId, kbId, orgId)
                .orElseThrow(() -> new ResourceNotFoundException("文档不存在"));

        // 校验权限:正向校验 owner/admin
        if (!"OWNER".equals(callerRole) && !"ADMIN".equals(callerRole)) {
            throw new AccessDeniedException("权限不足,仅 owner/admin 可删除文档");
        }

        // 先删 RAGFlow(跳过无 ragflowDocId 的记录)
        if (doc.getRagflowDocId() != null) {
            try {
                ragFlowClient.deleteDocument(doc.getKb().getRagflowDatasetId(), doc.getRagflowDocId());
            } catch (Exception e) {
                // RAGFlow 删除失败 → 用独立事务置 FAILED,保留 DB 记录
                log.error("删除 RAGFlow 文档失败,docId={}: {}", docId, e.getMessage());
                saveFailedStatus(docId, "RAGFlow 删除失败: " + e.getMessage());
                throw new RuntimeException("删除文档失败(RAGFlow): " + e.getMessage(), e);
            }
        }

        // 再删 DB
        documentRepository.delete(doc);
        log.info("文档已删除,docId={}", docId);
    }

    /**
     * 用 REQUIRES_NEW 独立事务保存文档 FAILED 状态
     * 解决外层事务回滚导致 FAILED 标记丢失的问题
     */
    private void saveFailedStatus(UUID docId, String errorMessage) {
        try {
            TransactionTemplate txTemplate = new TransactionTemplate(transactionManager);
            txTemplate.setPropagationBehavior(org.springframework.transaction.TransactionDefinition.PROPAGATION_REQUIRES_NEW);
            txTemplate.executeWithoutResult(status -> {
                documentRepository.findById(docId).ifPresent(doc -> {
                    doc.setStatus(DocumentStatus.FAILED);
                    doc.setErrorMessage(errorMessage);
                    documentRepository.save(doc);
                });
            });
        } catch (Exception ex) {
            log.error("保存 FAILED 状态失败(独立事务),docId={}: {}", docId, ex.getMessage());
        }
    }

    /** 提取文件扩展名(不含点号) */
    private String getExtension(String filename) {
        int lastDot = filename.lastIndexOf('.');
        if (lastDot < 0 || lastDot == filename.length() - 1) {
            return "";
        }
        return filename.substring(lastDot + 1);
    }
}
