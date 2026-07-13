package com.diit.ragkb;

import com.diit.ragkb.model.*;
import com.diit.ragkb.ragcore.storage.ObjectStorage;
import com.diit.ragkb.repository.*;
import com.diit.ragkb.service.DocumentDirectUploadService;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.io.*;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.*;
import static org.hamcrest.Matchers.containsString;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest(properties = {
        "rag.storage.type=local",
        "rag.upload.direct.ttl-seconds=900",
        "rag.observability.metrics-token=metrics-test-key",
        "management.endpoints.web.exposure.include=health,prometheus",
        "management.prometheus.metrics.export.enabled=true"
})
@AutoConfigureMockMvc
@Import(DocumentDirectUploadTest.DirectStorageConfig.class)
@DisplayName("生产级对象存储直传")
class DocumentDirectUploadTest {

    @Autowired MockMvc mockMvc;
    @Autowired TestHelper testHelper;
    @Autowired FakeDirectObjectStorage storage;
    @Autowired DocumentUploadSessionRepository sessionRepository;
    @Autowired IngestionJobRepository jobRepository;
    @Autowired KnowledgeDocumentRepository documentRepository;
    @Autowired KnowledgeBaseRepository knowledgeBaseRepository;
    @Autowired MemberRepository memberRepository;
    @Autowired OrganizationRepository organizationRepository;
    @Autowired UserRepository userRepository;
    @Autowired DocumentDirectUploadService directUploadService;

    private Organization org;
    private KnowledgeBase kb;
    private String token;

    @BeforeEach
    void setUp() {
        clean();
        User owner = testHelper.createUser("direct-owner@test.com", "Pass1234!", "Direct Owner");
        org = testHelper.createOrg("直传测试组织");
        Member member = testHelper.createMember(owner.getId().toString(), org, MemberRole.OWNER);
        token = testHelper.generateToken(owner.getId(), 0);
        kb = new KnowledgeBase();
        kb.setOrg(org);
        kb.setName("直传知识库");
        kb.setCreatedBy(member);
        kb = knowledgeBaseRepository.save(kb);
    }

    @AfterEach
    void tearDown() {
        clean();
    }

    @Test
    @DisplayName("完成回调校验对象后只创建一次文档和摄取任务")
    void complete_isIdempotentAndCreatesOneJob() throws Exception {
        String body = "{\"kbId\":\"" + kb.getId() + "\",\"fileName\":\"design.pdf\",\"sizeBytes\":8}";
        String response = mockMvc.perform(post("/api/v1/documents/uploads")
                        .header("Authorization", "Bearer " + token)
                        .header("X-Org-Id", org.getId().toString())
                        .header("Idempotency-Key", "upload-design-v1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.data.uploadUrl").value("https://storage.test/upload"))
                .andExpect(jsonPath("$.data.method").value("PUT"))
                .andReturn().getResponse().getContentAsString();

        String sessionId = response.replaceAll(".*\\\"sessionId\\\":\\\"([^\\\"]+)\\\".*", "$1");
        storage.finishLastUpload("%PDF-123".getBytes(), "application/pdf");

        mockMvc.perform(post("/api/v1/documents/uploads/{sessionId}/complete", sessionId)
                        .header("Authorization", "Bearer " + token)
                        .header("X-Org-Id", org.getId().toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.status").value("QUEUED"));

        mockMvc.perform(post("/api/v1/documents/uploads/{sessionId}/complete", sessionId)
                        .header("Authorization", "Bearer " + token)
                        .header("X-Org-Id", org.getId().toString()))
                .andExpect(status().isOk());

        assertEquals(1, documentRepository.count());
        assertEquals(1, jobRepository.count());
        KnowledgeDocument document = documentRepository.findAll().get(0);
        assertEquals("application/pdf", document.getContentType());
        assertNotNull(document.getContentSha256());
        assertEquals(64, document.getContentSha256().length());
        assertFalse(storage.transactionActiveDuringOpen,
                "对象全量读取不得长时间占用数据库事务");
        assertEquals(UploadSessionStatus.COMPLETED, sessionRepository.findById(java.util.UUID.fromString(sessionId)).orElseThrow().getStatus());
    }

    @Test
    @DisplayName("并发 complete 使用校验 token 串行化且只创建一份文档")
    void concurrentCompleteOnlyCreatesOneDocument() throws Exception {
        String body = "{\"kbId\":\"" + kb.getId() + "\",\"fileName\":\"concurrent.pdf\",\"sizeBytes\":8}";
        String response = mockMvc.perform(post("/api/v1/documents/uploads")
                        .header("Authorization", "Bearer " + token)
                        .header("X-Org-Id", org.getId().toString())
                        .header("Idempotency-Key", "concurrent-complete")
                        .contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isCreated()).andReturn().getResponse().getContentAsString();
        String sessionId = response.replaceAll(".*\\\"sessionId\\\":\\\"([^\\\"]+)\\\".*", "$1");
        storage.finishLastUpload("%PDF-123".getBytes(), "application/pdf");
        storage.blockReads();

        CompletableFuture<Integer> first = CompletableFuture.supplyAsync(() -> {
            try {
                return mockMvc.perform(post("/api/v1/documents/uploads/{sessionId}/complete", sessionId)
                                .header("Authorization", "Bearer " + token)
                                .header("X-Org-Id", org.getId().toString()))
                        .andReturn().getResponse().getStatus();
            } catch (Exception ex) {
                throw new RuntimeException(ex);
            }
        });
        assertTrue(storage.awaitReadStarted(), "第一个 complete 未进入对象校验");

        mockMvc.perform(post("/api/v1/documents/uploads/{sessionId}/complete", sessionId)
                        .header("Authorization", "Bearer " + token)
                        .header("X-Org-Id", org.getId().toString()))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.message").value(containsString("正在校验")));

        storage.releaseReads();
        assertEquals(200, first.get(10, TimeUnit.SECONDS));
        assertEquals(1, documentRepository.count());
        assertEquals(1, jobRepository.count());
    }

    @Test
    @DisplayName("直传完成时拒绝与扩展名不匹配的伪装文件")
    void completeRejectsSpoofedContent() throws Exception {
        String body = "{\"kbId\":\"" + kb.getId() + "\",\"fileName\":\"spoofed.pdf\",\"sizeBytes\":8}";
        String response = mockMvc.perform(post("/api/v1/documents/uploads")
                        .header("Authorization", "Bearer " + token)
                        .header("X-Org-Id", org.getId().toString())
                        .header("Idempotency-Key", "spoofed-upload")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();
        String sessionId = response.replaceAll(".*\\\"sessionId\\\":\\\"([^\\\"]+)\\\".*", "$1");
        storage.finishLastUpload("NOT-PDF!".getBytes(), "application/pdf");

        mockMvc.perform(post("/api/v1/documents/uploads/{sessionId}/complete", sessionId)
                        .header("Authorization", "Bearer " + token)
                        .header("X-Org-Id", org.getId().toString()))
                .andExpect(status().isBadRequest());

        assertEquals(0, documentRepository.count());
        assertEquals(0, jobRepository.count());
    }

    @Test
    @DisplayName("相同幂等键返回原会话，对象大小不一致时不创建任务")
    void initiateIsIdempotentAndCompleteRejectsWrongSize() throws Exception {
        String body = "{\"kbId\":\"" + kb.getId() + "\",\"fileName\":\"slides.pptx\",\"sizeBytes\":100}";
        for (int i = 0; i < 2; i++) {
            mockMvc.perform(post("/api/v1/documents/uploads")
                            .header("Authorization", "Bearer " + token)
                            .header("X-Org-Id", org.getId().toString())
                            .header("Idempotency-Key", "same-key")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content(body))
                    .andExpect(status().isCreated());
        }
        assertEquals(1, sessionRepository.count());
        DocumentUploadSession session = sessionRepository.findAll().get(0);
        storage.finishLastUpload(new byte[10], "application/octet-stream");

        mockMvc.perform(post("/api/v1/documents/uploads/{sessionId}/complete", session.getId())
                        .header("Authorization", "Bearer " + token)
                        .header("X-Org-Id", org.getId().toString()))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value(409));
        assertEquals(0, documentRepository.count());
        assertEquals(0, jobRepository.count());
    }

    @Test
    @DisplayName("Prometheus 指标端点必须使用独立密钥且能暴露上传指标")
    void prometheusEndpointRequiresMetricsKey() throws Exception {
        String body = "{\"kbId\":\"" + kb.getId() + "\",\"fileName\":\"metrics.pdf\",\"sizeBytes\":8}";
        mockMvc.perform(post("/api/v1/documents/uploads")
                        .header("Authorization", "Bearer " + token)
                        .header("X-Org-Id", org.getId().toString())
                        .header("Idempotency-Key", "metrics-upload")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isCreated());

        mockMvc.perform(get("/actuator/prometheus"))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/actuator/prometheus").header("X-Metrics-Key", "metrics-test-key"))
                .andExpect(status().isOk())
                .andExpect(content().string(containsString("rag_upload_sessions_total")));
    }

    @Test
    @DisplayName("过期会话按独立事务清理对象并进入 EXPIRED")
    void cleanupExpiresSessionAndDeletesStagingObject() throws Exception {
        String body = "{\"kbId\":\"" + kb.getId() + "\",\"fileName\":\"expired.pdf\",\"sizeBytes\":8}";
        mockMvc.perform(post("/api/v1/documents/uploads")
                        .header("Authorization", "Bearer " + token)
                        .header("X-Org-Id", org.getId().toString())
                        .header("Idempotency-Key", "expired-upload")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isCreated());
        storage.finishLastUpload("%PDF-12".getBytes(), "application/pdf");
        DocumentUploadSession session = sessionRepository.findAll().get(0);
        session.setExpiresAt(Instant.now().minusSeconds(1));
        sessionRepository.saveAndFlush(session);

        directUploadService.cleanupExpiredSessions();

        assertEquals(UploadSessionStatus.EXPIRED, sessionRepository.findById(session.getId()).orElseThrow().getStatus());
        assertFalse(storage.contains(session.getObjectStoragePath()));
    }

    @Test
    @DisplayName("校验 Worker 崩溃后超时 VERIFYING 会话可恢复为 PENDING")
    void cleanupRecoversStaleVerificationLease() throws Exception {
        String body = "{\"kbId\":\"" + kb.getId() + "\",\"fileName\":\"recover.pdf\",\"sizeBytes\":8}";
        mockMvc.perform(post("/api/v1/documents/uploads")
                        .header("Authorization", "Bearer " + token)
                        .header("X-Org-Id", org.getId().toString())
                        .header("Idempotency-Key", "recover-verification")
                        .contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isCreated());
        DocumentUploadSession session = sessionRepository.findAll().get(0);
        session.setStatus(UploadSessionStatus.VERIFYING);
        session.setVerificationToken(java.util.UUID.randomUUID());
        session.setVerificationStartedAt(Instant.now().minus(Duration.ofMinutes(20)));
        sessionRepository.saveAndFlush(session);

        directUploadService.cleanupExpiredSessions();

        DocumentUploadSession recovered = sessionRepository.findById(session.getId()).orElseThrow();
        assertEquals(UploadSessionStatus.PENDING, recovered.getStatus());
        assertNull(recovered.getVerificationToken());
        assertNull(recovered.getVerificationStartedAt());
    }

    private void clean() {
        sessionRepository.deleteAll();
        jobRepository.deleteAll();
        documentRepository.deleteAll();
        knowledgeBaseRepository.deleteAll();
        memberRepository.deleteAll();
        organizationRepository.deleteAll();
        userRepository.deleteAll();
        storage.clear();
    }

    @TestConfiguration
    static class DirectStorageConfig {
        @Bean
        @Primary
        FakeDirectObjectStorage fakeDirectObjectStorage() {
            return new FakeDirectObjectStorage();
        }
    }

    static class FakeDirectObjectStorage implements ObjectStorage {
        private final Map<String, byte[]> objects = new ConcurrentHashMap<>();
        private String lastKey;
        private String lastContentType;
        private volatile boolean transactionActiveDuringOpen;
        private volatile CountDownLatch readStarted = new CountDownLatch(0);
        private volatile CountDownLatch releaseRead = new CountDownLatch(0);

        @Override public void put(String objectKey, InputStream input, long sizeBytes, String contentType) throws IOException {
            objects.put(objectKey, input.readAllBytes());
            lastContentType = contentType;
        }
        @Override public InputStream open(String objectKey) {
            transactionActiveDuringOpen = TransactionSynchronizationManager.isActualTransactionActive();
            readStarted.countDown();
            try {
                if (!releaseRead.await(10, TimeUnit.SECONDS)) throw new IllegalStateException("等待释放校验超时");
            } catch (InterruptedException ex) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException("校验线程被中断", ex);
            }
            return new ByteArrayInputStream(objects.get(objectKey));
        }
        @Override public void delete(String objectKey) { objects.remove(objectKey); }
        @Override public boolean supportsDirectUpload() { return true; }
        @Override public PresignedUpload presignPut(String objectKey, String contentType, Duration ttl) {
            lastKey = objectKey;
            lastContentType = contentType;
            return new PresignedUpload("https://storage.test/upload", "PUT", Map.of("Content-Type", contentType), Instant.now().plus(ttl));
        }
        @Override public StoredObject stat(String objectKey) throws IOException {
            byte[] value = objects.get(objectKey);
            if (value == null) throw new IOException("not found");
            return new StoredObject(value.length, lastContentType, "test-etag");
        }
        void finishLastUpload(byte[] value, String contentType) { objects.put(lastKey, value); lastContentType = contentType; }
        void blockReads() { readStarted = new CountDownLatch(1); releaseRead = new CountDownLatch(1); }
        boolean awaitReadStarted() throws InterruptedException { return readStarted.await(10, TimeUnit.SECONDS); }
        void releaseReads() { releaseRead.countDown(); }
        boolean contains(String key) { return objects.containsKey(key); }
        void clear() {
            objects.clear();
            lastKey = null;
            transactionActiveDuringOpen = false;
            readStarted = new CountDownLatch(0);
            releaseRead = new CountDownLatch(0);
        }
    }
}
