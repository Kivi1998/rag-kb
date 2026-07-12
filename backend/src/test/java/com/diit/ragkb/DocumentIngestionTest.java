package com.diit.ragkb;

import com.diit.ragkb.model.IngestionJob;
import com.diit.ragkb.model.KnowledgeBase;
import com.diit.ragkb.model.Member;
import com.diit.ragkb.model.MemberRole;
import com.diit.ragkb.model.Organization;
import com.diit.ragkb.model.User;
import com.diit.ragkb.ragcore.model.IngestionStatus;
import com.diit.ragkb.ragcore.ingestion.IngestionJobLifecycleService;
import com.diit.ragkb.repository.IngestionJobRepository;
import com.diit.ragkb.repository.KnowledgeBaseRepository;
import com.diit.ragkb.repository.KnowledgeDocumentRepository;
import com.diit.ragkb.repository.MemberRepository;
import com.diit.ragkb.repository.OrganizationRepository;
import com.diit.ragkb.repository.UserRepository;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.web.servlet.MockMvc;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.Comparator;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 文档上传 API 与异步摄取任务创建的集成测试。 */
@SpringBootTest(properties = {
        "rag.storage.type=local",
        "rag.storage.local-root=target/test-rag-objects"
})
@AutoConfigureMockMvc
@DisplayName("文档摄取基础能力")
class DocumentIngestionTest {

    private static final Path OBJECT_ROOT = Path.of("target/test-rag-objects");

    @Autowired private MockMvc mockMvc;
    @Autowired private TestHelper testHelper;
    @Autowired private IngestionJobRepository jobRepository;
    @Autowired private IngestionJobLifecycleService lifecycleService;
    @Autowired private KnowledgeDocumentRepository documentRepository;
    @Autowired private KnowledgeBaseRepository knowledgeBaseRepository;
    @Autowired private MemberRepository memberRepository;
    @Autowired private OrganizationRepository organizationRepository;
    @Autowired private UserRepository userRepository;

    private Organization org;
    private KnowledgeBase knowledgeBase;
    private String ownerToken;
    private String memberToken;

    @BeforeEach
    void setUp() throws IOException {
        cleanDatabaseAndObjects();
        User owner = testHelper.createUser("doc-owner@test.com", "Pass1234!", "Doc Owner");
        User member = testHelper.createUser("doc-member@test.com", "Pass1234!", "Doc Member");
        org = testHelper.createOrg("文档测试组织");
        Member ownerMember = testHelper.createMember(owner.getId().toString(), org, MemberRole.OWNER);
        testHelper.createMember(member.getId().toString(), org, MemberRole.MEMBER);
        ownerToken = testHelper.generateToken(owner.getId(), 0);
        memberToken = testHelper.generateToken(member.getId(), 0);

        knowledgeBase = new KnowledgeBase();
        knowledgeBase.setOrg(org);
        knowledgeBase.setName("技术文档库");
        knowledgeBase.setCreatedBy(ownerMember);
        knowledgeBase = knowledgeBaseRepository.save(knowledgeBase);
    }

    @AfterEach
    void tearDown() throws IOException {
        cleanDatabaseAndObjects();
    }

    @Test
    @DisplayName("Owner 上传 Markdown 后创建 QUEUED 文档和摄取任务")
    void ownerUpload_createsQueuedDocumentAndJob() throws Exception {
        mockMvc.perform(multipart("/api/v1/documents/upload")
                        .file(new MockMultipartFile("file", "架构说明.md", "text/markdown", "# 架构\n正文".getBytes()))
                        .param("kbId", knowledgeBase.getId().toString())
                        .header("Authorization", "Bearer " + ownerToken)
                        .header("X-Org-Id", org.getId().toString()))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.name").value("架构说明.md"))
                .andExpect(jsonPath("$.data.kbId").value(knowledgeBase.getId().toString()))
                .andExpect(jsonPath("$.data.status").value("QUEUED"))
                .andExpect(jsonPath("$.data.jobId").isNotEmpty())
                .andExpect(jsonPath("$.data.sourcePath").doesNotExist());

        var documents = documentRepository.findByKnowledgeBaseIdAndOrgIdOrderByCreatedAtDesc(knowledgeBase.getId(), org.getId());
        assertEquals(1, documents.size());
        assertTrue(documents.get(0).getObjectStoragePath().endsWith(".md"));
        assertNotNull(documents.get(0).getContentSha256());
        assertEquals(64, documents.get(0).getContentSha256().length());
        IngestionJob job = jobRepository.findFirstByDocumentIdOrderByCreatedAtDesc(documents.get(0).getId()).orElseThrow();
        assertEquals(IngestionStatus.QUEUED, job.getStatus());

        mockMvc.perform(get("/api/v1/documents/jobs/{jobId}", job.getId())
                        .param("kbId", knowledgeBase.getId().toString())
                        .header("Authorization", "Bearer " + ownerToken)
                        .header("X-Org-Id", org.getId().toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.jobId").value(job.getId().toString()))
                .andExpect(jsonPath("$.data.status").value("QUEUED"));
    }

    @Test
    @DisplayName("普通成员不能上传文档")
    void memberUpload_isForbidden() throws Exception {
        mockMvc.perform(multipart("/api/v1/documents/upload")
                        .file(new MockMultipartFile("file", "guide.md", "text/markdown", "# guide".getBytes()))
                        .param("kbId", knowledgeBase.getId().toString())
                        .header("Authorization", "Bearer " + memberToken)
                        .header("X-Org-Id", org.getId().toString()))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value(403));
    }

    @Test
    @DisplayName("不支持的文件扩展名返回 400")
    void unsupportedExtension_isBadRequest() throws Exception {
        mockMvc.perform(multipart("/api/v1/documents/upload")
                        .file(new MockMultipartFile("file", "unsafe.exe", "application/octet-stream", new byte[]{1}))
                        .param("kbId", knowledgeBase.getId().toString())
                        .header("Authorization", "Bearer " + ownerToken)
                        .header("X-Org-Id", org.getId().toString()))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(400));
    }

    @Test
    @DisplayName("伪装为 PDF 的非 PDF 内容在上传阶段被拒绝")
    void fakePdfContent_isRejectedBeforeIngestion() throws Exception {
        mockMvc.perform(multipart("/api/v1/documents/upload")
                        .file(new MockMultipartFile("file", "fake.pdf", "application/pdf", "not-a-pdf".getBytes()))
                        .param("kbId", knowledgeBase.getId().toString())
                        .header("Authorization", "Bearer " + ownerToken)
                        .header("X-Org-Id", org.getId().toString()))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(400));

        assertTrue(documentRepository.findByKnowledgeBaseIdAndOrgIdOrderByCreatedAtDesc(knowledgeBase.getId(), org.getId()).isEmpty());
    }

    @Test
    @DisplayName("任务只允许一个 Worker 领取，失败后管理员可重试")
    void lifecycle_claimFailAndRetry_keepsDocumentInSync() throws Exception {
        mockMvc.perform(multipart("/api/v1/documents/upload")
                        .file(new MockMultipartFile("file", "worker.md", "text/markdown", "# worker".getBytes()))
                        .param("kbId", knowledgeBase.getId().toString())
                        .header("Authorization", "Bearer " + ownerToken)
                        .header("X-Org-Id", org.getId().toString()))
                .andExpect(status().isCreated());

        var document = documentRepository.findByKnowledgeBaseIdAndOrgIdOrderByCreatedAtDesc(knowledgeBase.getId(), org.getId()).get(0);
        IngestionJob job = jobRepository.findFirstByDocumentIdOrderByCreatedAtDesc(document.getId()).orElseThrow();

        assertTrue(lifecycleService.claim(job.getId()).isPresent());
        assertTrue(lifecycleService.claim(job.getId()).isEmpty());
        lifecycleService.fail(job.getId(), new IllegalStateException("模拟解析失败"));

        IngestionJob failed = jobRepository.findById(job.getId()).orElseThrow();
        assertEquals(IngestionStatus.FAILED, failed.getStatus());
        assertEquals(1, failed.getAttempt());
        assertEquals(IngestionStatus.FAILED,
                documentRepository.findById(document.getId()).orElseThrow().getStatus());

        mockMvc.perform(post("/api/v1/documents/jobs/{jobId}/retry", job.getId())
                        .param("kbId", knowledgeBase.getId().toString())
                        .header("Authorization", "Bearer " + ownerToken)
                        .header("X-Org-Id", org.getId().toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.status").value("QUEUED"));

        assertEquals(IngestionStatus.QUEUED, jobRepository.findById(job.getId()).orElseThrow().getStatus());
        assertEquals(1, documentRepository.findById(document.getId()).orElseThrow().getRetryCount());
    }

    @Test
    @DisplayName("过期 Worker 租约会恢复任务，避免进程异常后文档永久卡住")
    void expiredLease_isRecoveredToQueue() throws Exception {
        mockMvc.perform(multipart("/api/v1/documents/upload")
                        .file(new MockMultipartFile("file", "recover.md", "text/markdown", "# recover".getBytes()))
                        .param("kbId", knowledgeBase.getId().toString())
                        .header("Authorization", "Bearer " + ownerToken)
                        .header("X-Org-Id", org.getId().toString()))
                .andExpect(status().isCreated());

        var document = documentRepository.findByKnowledgeBaseIdAndOrgIdOrderByCreatedAtDesc(knowledgeBase.getId(), org.getId()).get(0);
        IngestionJob job = jobRepository.findFirstByDocumentIdOrderByCreatedAtDesc(document.getId()).orElseThrow();
        assertTrue(lifecycleService.claim(job.getId(), "crashed-worker", Duration.ofMinutes(1)).isPresent());

        job = jobRepository.findById(job.getId()).orElseThrow();
        assertEquals("crashed-worker", job.getLeaseOwner());
        assertNotNull(job.getLeaseExpiresAt());
        job.setLeaseExpiresAt(Instant.now().minusSeconds(1));
        jobRepository.save(job);

        assertEquals(1, lifecycleService.recoverExpiredLeases());
        job = jobRepository.findById(job.getId()).orElseThrow();
        assertEquals(IngestionStatus.QUEUED, job.getStatus());
        assertNull(job.getLeaseOwner());
        assertNull(job.getLeaseExpiresAt());
        assertEquals(IngestionStatus.QUEUED, documentRepository.findById(document.getId()).orElseThrow().getStatus());
    }

    @Test
    @DisplayName("删除文档会清理对象、任务与文档元数据")
    void deleteDocument_cleansJobAndMetadata() throws Exception {
        mockMvc.perform(multipart("/api/v1/documents/upload")
                        .file(new MockMultipartFile("file", "remove.md", "text/markdown", "# remove".getBytes()))
                        .param("kbId", knowledgeBase.getId().toString())
                        .header("Authorization", "Bearer " + ownerToken)
                        .header("X-Org-Id", org.getId().toString()))
                .andExpect(status().isCreated());
        var document = documentRepository.findByKnowledgeBaseIdAndOrgIdOrderByCreatedAtDesc(knowledgeBase.getId(), org.getId()).get(0);

        mockMvc.perform(delete("/api/v1/documents/{documentId}", document.getId())
                        .param("kbId", knowledgeBase.getId().toString())
                        .header("Authorization", "Bearer " + ownerToken)
                        .header("X-Org-Id", org.getId().toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0));

        assertTrue(documentRepository.findById(document.getId()).isEmpty());
        assertTrue(jobRepository.findFirstByDocumentIdOrderByCreatedAtDesc(document.getId()).isEmpty());
    }

    private void cleanDatabaseAndObjects() throws IOException {
        jobRepository.deleteAll();
        documentRepository.deleteAll();
        knowledgeBaseRepository.deleteAll();
        memberRepository.deleteAll();
        organizationRepository.deleteAll();
        userRepository.deleteAll();
        if (Files.exists(OBJECT_ROOT)) {
            try (var paths = Files.walk(OBJECT_ROOT)) {
                paths.sorted(Comparator.reverseOrder()).forEach(path -> {
                    try {
                        Files.delete(path);
                    } catch (IOException ex) {
                        throw new IllegalStateException("清理测试对象存储失败", ex);
                    }
                });
            }
        }
    }
}
