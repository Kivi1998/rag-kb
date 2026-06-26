package com.diit.ragkb;

import com.diit.ragkb.model.*;
import com.diit.ragkb.repository.*;
import com.diit.ragkb.service.ragflow.RagFlowClient;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

import java.util.UUID;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * 文档管理测试
 */
@SpringBootTest
@AutoConfigureMockMvc
@DisplayName("文档管理测试")
class DocumentTest {

    @Autowired private MockMvc mockMvc;
    @Autowired private TestHelper testHelper;
    @Autowired private ObjectMapper objectMapper;
    @Autowired private MemberRepository memberRepository;
    @Autowired private OrganizationRepository organizationRepository;
    @Autowired private KnowledgeBaseRepository knowledgeBaseRepository;
    @Autowired private DocumentRepository documentRepository;
    @Autowired private UserRepository userRepository;

    @MockBean
    private RagFlowClient ragFlowClient;

    private Organization orgA, orgB;
    private KnowledgeBase kbA, kbB;
    private User userOwnerA, userAdminA, userMemberA, userOwnerB;
    private String ownerAToken, adminAToken, memberAToken, ownerBToken;

    @BeforeEach
    void setUp() {
        // 清理数据
        documentRepository.deleteAll();
        knowledgeBaseRepository.deleteAll();
        memberRepository.deleteAll();
        organizationRepository.deleteAll();
        userRepository.deleteAll();

        // 重置 mock
        reset(ragFlowClient);

        // 创建用户
        userOwnerA  = testHelper.createUser("owner-a@test.com",  "Pass1234!", "Owner A");
        userAdminA  = testHelper.createUser("admin-a@test.com",  "Pass1234!", "Admin A");
        userMemberA = testHelper.createUser("member-a@test.com", "Pass1234!", "Member A");
        userOwnerB  = testHelper.createUser("owner-b@test.com",  "Pass1234!", "Owner B");

        // 创建组织
        orgA = testHelper.createOrg("测试组织A");
        orgB = testHelper.createOrg("测试组织B");

        // 创建成员
        Member memberOwnerA = testHelper.createMember(userOwnerA.getId().toString(),  orgA, MemberRole.OWNER);
        testHelper.createMember(userAdminA.getId().toString(),  orgA, MemberRole.ADMIN);
        testHelper.createMember(userMemberA.getId().toString(), orgA, MemberRole.MEMBER);
        Member memberOwnerB = testHelper.createMember(userOwnerB.getId().toString(),  orgB, MemberRole.OWNER);

        // 创建知识库
        kbA = new KnowledgeBase();
        kbA.setOrg(orgA);
        kbA.setName("知识库A");
        kbA.setRagflowDatasetId("ds-a-" + UUID.randomUUID());
        kbA.setCreatedBy(memberOwnerA);
        kbA = knowledgeBaseRepository.save(kbA);

        kbB = new KnowledgeBase();
        kbB.setOrg(orgB);
        kbB.setName("知识库B");
        kbB.setRagflowDatasetId("ds-b-" + UUID.randomUUID());
        kbB.setCreatedBy(memberOwnerB);
        kbB = knowledgeBaseRepository.save(kbB);

        // 生成 JWT
        ownerAToken  = testHelper.generateToken(userOwnerA.getId(), 0);
        adminAToken  = testHelper.generateToken(userAdminA.getId(), 0);
        memberAToken = testHelper.generateToken(userMemberA.getId(), 0);
        ownerBToken  = testHelper.generateToken(userOwnerB.getId(), 0);

        // Mock RagFlowClient 默认行为
        when(ragFlowClient.uploadDocument(anyString(), anyString(), any(), anyString()))
                .thenReturn("ragflow-doc-" + UUID.randomUUID());
        doNothing().when(ragFlowClient).parseDocument(anyString(), anyString());
        doNothing().when(ragFlowClient).deleteDocument(anyString(), anyString());
    }

    /**
     * 创建测试用 MockMultipartFile
     */
    private MockMultipartFile createTestFile(String filename, String contentType) {
        byte[] content = "test file content".getBytes();
        return new MockMultipartFile("file", filename, contentType, content);
    }

    // ===== 5.1 正常上传测试 =====
    @Nested
    @DisplayName("5.1 正常上传")
    class NormalUploadTests {
        @Test
        @DisplayName("合法文件类型 → 201 + docId + 状态 PARSING")
        void upload_validFile_returns201() throws Exception {
            MockMultipartFile file = createTestFile("test.pdf", "application/pdf");

            mockMvc.perform(multipart("/api/v1/knowledge-bases/{kbId}/documents", kbA.getId())
                            .file(file)
                            .header("Authorization", "Bearer " + memberAToken)
                            .header("X-Org-Id", orgA.getId()))
                    .andExpect(status().isCreated())
                    .andExpect(jsonPath("$.data.name").value("test.pdf"))
                    .andExpect(jsonPath("$.data.status").value("PARSING"));
        }

        @Test
        @DisplayName("admin 上传 → 201")
        void upload_byAdmin_returns201() throws Exception {
            MockMultipartFile file = createTestFile("doc.docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document");

            mockMvc.perform(multipart("/api/v1/knowledge-bases/{kbId}/documents", kbA.getId())
                            .file(file)
                            .header("Authorization", "Bearer " + adminAToken)
                            .header("X-Org-Id", orgA.getId()))
                    .andExpect(status().isCreated())
                    .andExpect(jsonPath("$.data.status").value("PARSING"));
        }
    }

    // ===== 5.2 非法文件类型上传 → 400 =====
    @Nested
    @DisplayName("5.2 非法文件类型")
    class InvalidFileTypeTests {
        @Test
        @DisplayName("上传 .exe → 400")
        void upload_exe_returns400() throws Exception {
            MockMultipartFile file = createTestFile("malware.exe", "application/octet-stream");

            mockMvc.perform(multipart("/api/v1/knowledge-bases/{kbId}/documents", kbA.getId())
                            .file(file)
                            .header("Authorization", "Bearer " + memberAToken)
                            .header("X-Org-Id", orgA.getId()))
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.code").value(400));
        }

        @Test
        @DisplayName("上传 .zip → 400")
        void upload_zip_returns400() throws Exception {
            MockMultipartFile file = createTestFile("archive.zip", "application/zip");

            mockMvc.perform(multipart("/api/v1/knowledge-bases/{kbId}/documents", kbA.getId())
                            .file(file)
                            .header("Authorization", "Bearer " + memberAToken)
                            .header("X-Org-Id", orgA.getId()))
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.code").value(400));
        }
    }

    // ===== 5.3 文件超限上传 → 400 =====
    // MockMvc 不触发 servlet 级 multipart 限制,超限由 service 层 IllegalArgumentException 捕获 → 400
    // MaxUploadSizeExceededException → 413 的 handler 已注册,真实环境生效
    @Nested
    @DisplayName("5.3 文件超限")
    class FileTooLargeTests {
        @Test
        @DisplayName("超过 50MB → 400(MockMvc 环境)")
        void upload_tooLarge_returns400() throws Exception {
            // 创建超过 50MB 的文件
            byte[] largeContent = new byte[51 * 1024 * 1024]; // 51MB
            MockMultipartFile file = new MockMultipartFile("file", "large.pdf", "application/pdf", largeContent);

            mockMvc.perform(multipart("/api/v1/knowledge-bases/{kbId}/documents", kbA.getId())
                            .file(file)
                            .header("Authorization", "Bearer " + memberAToken)
                            .header("X-Org-Id", orgA.getId()))
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.code").value(400));
        }
    }

    // ===== 5.4 文档列表测试 =====
    @Nested
    @DisplayName("5.4 文档列表")
    class DocumentListTests {
        @Test
        @DisplayName("只返回本组织知识库文档")
        void list_onlyOwnOrgDocs() throws Exception {
            // 在 orgA 的知识库中创建文档
            Document doc = new Document();
            doc.setKb(kbA);
            doc.setOrg(orgA);
            doc.setName("doc-a.pdf");
            doc.setSizeBytes(1024);
            doc.setStatus(DocumentStatus.PARSING);
            documentRepository.save(doc);

            // orgB 查询 → 看不到 orgA 的文档
            mockMvc.perform(get("/api/v1/knowledge-bases/{kbId}/documents", kbA.getId())
                            .header("Authorization", "Bearer " + ownerBToken)
                            .header("X-Org-Id", orgB.getId()))
                    .andExpect(status().isNotFound()); // 跨租户 KB → 404
        }

        @Test
        @DisplayName("本组织列表 → 返回文档")
        void list_ownOrg_returnsDocs() throws Exception {
            Document doc = new Document();
            doc.setKb(kbA);
            doc.setOrg(orgA);
            doc.setName("doc-a.pdf");
            doc.setSizeBytes(1024);
            doc.setStatus(DocumentStatus.READY);
            documentRepository.save(doc);

            mockMvc.perform(get("/api/v1/knowledge-bases/{kbId}/documents", kbA.getId())
                            .header("Authorization", "Bearer " + memberAToken)
                            .header("X-Org-Id", orgA.getId()))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.length()").value(1))
                    .andExpect(jsonPath("$.data[0].name").value("doc-a.pdf"));
        }
    }

    // ===== 5.5 文档状态查询 =====
    @Nested
    @DisplayName("5.5 文档状态查询")
    class DocumentStatusTests {
        @Test
        @DisplayName("PARSING 状态触发 RAGFlow 查询")
        void getById_parsingStatus_queriesRagFlow() throws Exception {
            Document doc = new Document();
            doc.setKb(kbA);
            doc.setOrg(orgA);
            doc.setName("parsing.pdf");
            doc.setSizeBytes(1024);
            doc.setStatus(DocumentStatus.PARSING);
            doc.setRagflowDocId("rf-doc-123");
            doc = documentRepository.save(doc);

            // Mock RAGFlow 返回解析完成
            when(ragFlowClient.getDocumentStatus(kbA.getRagflowDatasetId(), "rf-doc-123"))
                    .thenReturn("3"); // run=3 表示解析完成

            mockMvc.perform(get("/api/v1/knowledge-bases/{kbId}/documents/{docId}", kbA.getId(), doc.getId())
                            .header("Authorization", "Bearer " + memberAToken)
                            .header("X-Org-Id", orgA.getId()))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.status").value("READY"));

            // 验证调用了 RAGFlow
            verify(ragFlowClient).getDocumentStatus(kbA.getRagflowDatasetId(), "rf-doc-123");
        }

        @Test
        @DisplayName("READY 状态不触发 RAGFlow 查询")
        void getById_readyStatus_noRagFlowQuery() throws Exception {
            Document doc = new Document();
            doc.setKb(kbA);
            doc.setOrg(orgA);
            doc.setName("ready.pdf");
            doc.setSizeBytes(1024);
            doc.setStatus(DocumentStatus.READY);
            doc.setRagflowDocId("rf-doc-456");
            doc = documentRepository.save(doc);

            mockMvc.perform(get("/api/v1/knowledge-bases/{kbId}/documents/{docId}", kbA.getId(), doc.getId())
                            .header("Authorization", "Bearer " + memberAToken)
                            .header("X-Org-Id", orgA.getId()))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.status").value("READY"));

            // 验证未调用 RAGFlow
            verify(ragFlowClient, never()).getDocumentStatus(anyString(), anyString());
        }
    }

    // ===== 5.6 文档删除 =====
    @Nested
    @DisplayName("5.6 文档删除")
    class DocumentDeleteTests {
        @Test
        @DisplayName("admin 成功删除 → 200")
        void delete_byAdmin_returns200() throws Exception {
            Document doc = new Document();
            doc.setKb(kbA);
            doc.setOrg(orgA);
            doc.setName("to-delete.pdf");
            doc.setSizeBytes(1024);
            doc.setStatus(DocumentStatus.READY);
            doc.setRagflowDocId("rf-doc-del");
            doc = documentRepository.save(doc);

            mockMvc.perform(delete("/api/v1/knowledge-bases/{kbId}/documents/{docId}", kbA.getId(), doc.getId())
                            .header("Authorization", "Bearer " + adminAToken)
                            .header("X-Org-Id", orgA.getId()))
                    .andExpect(status().isOk());

            // 验证 RAGFlow 删除被调用
            verify(ragFlowClient).deleteDocument(kbA.getRagflowDatasetId(), "rf-doc-del");
        }

        @Test
        @DisplayName("member 删除 → 403")
        void delete_byMember_returns403() throws Exception {
            Document doc = new Document();
            doc.setKb(kbA);
            doc.setOrg(orgA);
            doc.setName("to-delete.pdf");
            doc.setSizeBytes(1024);
            doc.setStatus(DocumentStatus.READY);
            doc.setRagflowDocId("rf-doc-del");
            doc = documentRepository.save(doc);

            mockMvc.perform(delete("/api/v1/knowledge-bases/{kbId}/documents/{docId}", kbA.getId(), doc.getId())
                            .header("Authorization", "Bearer " + memberAToken)
                            .header("X-Org-Id", orgA.getId()))
                    .andExpect(status().isForbidden())
                    .andExpect(jsonPath("$.code").value(403));
        }
    }

    // ===== 5.7 跨租户安全测试 =====
    @Nested
    @DisplayName("5.7 跨租户安全")
    class CrossTenantTests {
        @Test
        @DisplayName("同组织跨 KB 查询 → 404")
        void crossKbQuery_returns404() throws Exception {
            // doc 属于 kbA
            Document doc = new Document();
            doc.setKb(kbA);
            doc.setOrg(orgA);
            doc.setName("secret.pdf");
            doc.setSizeBytes(1024);
            doc.setStatus(DocumentStatus.READY);
            doc = documentRepository.save(doc);

            // memberA 通过 kbB 的 URL 查询 kbA 的 doc → 404
            mockMvc.perform(get("/api/v1/knowledge-bases/{kbId}/documents/{docId}", kbB.getId(), doc.getId())
                            .header("Authorization", "Bearer " + memberAToken)
                            .header("X-Org-Id", orgA.getId()))
                    .andExpect(status().isNotFound());
        }

        @Test
        @DisplayName("同组织跨 KB 删除 → 404")
        void crossKbDelete_returns404() throws Exception {
            Document doc = new Document();
            doc.setKb(kbA);
            doc.setOrg(orgA);
            doc.setName("secret.pdf");
            doc.setSizeBytes(1024);
            doc.setStatus(DocumentStatus.READY);
            doc.setRagflowDocId("rf-doc-cross");
            doc = documentRepository.save(doc);

            // adminA 通过 kbB 的 URL 删除 kbA 的 doc → 404
            mockMvc.perform(delete("/api/v1/knowledge-bases/{kbId}/documents/{docId}", kbB.getId(), doc.getId())
                            .header("Authorization", "Bearer " + adminAToken)
                            .header("X-Org-Id", orgA.getId()))
                    .andExpect(status().isNotFound());
        }

        @Test
        @DisplayName("跨组织上传 → 404")
        void crossOrgUpload_returns404() throws Exception {
            MockMultipartFile file = createTestFile("test.pdf", "application/pdf");

            // ownerB 尝试上传到 orgA 的知识库
            mockMvc.perform(multipart("/api/v1/knowledge-bases/{kbId}/documents", kbA.getId())
                            .file(file)
                            .header("Authorization", "Bearer " + ownerBToken)
                            .header("X-Org-Id", orgB.getId()))
                    .andExpect(status().isNotFound());
        }

        @Test
        @DisplayName("跨组织查询 → 404")
        void crossOrgQuery_returns404() throws Exception {
            Document doc = new Document();
            doc.setKb(kbA);
            doc.setOrg(orgA);
            doc.setName("secret.pdf");
            doc.setSizeBytes(1024);
            doc.setStatus(DocumentStatus.READY);
            doc = documentRepository.save(doc);

            // ownerB 尝试查询 orgA 文档
            mockMvc.perform(get("/api/v1/knowledge-bases/{kbId}/documents/{docId}", kbA.getId(), doc.getId())
                            .header("Authorization", "Bearer " + ownerBToken)
                            .header("X-Org-Id", orgB.getId()))
                    .andExpect(status().isNotFound());
        }

        @Test
        @DisplayName("跨组织删除 → 404")
        void crossOrgDelete_returns404() throws Exception {
            Document doc = new Document();
            doc.setKb(kbA);
            doc.setOrg(orgA);
            doc.setName("secret.pdf");
            doc.setSizeBytes(1024);
            doc.setStatus(DocumentStatus.READY);
            doc.setRagflowDocId("rf-doc-secret");
            doc = documentRepository.save(doc);

            // ownerB 尝试删除 orgA 文档
            mockMvc.perform(delete("/api/v1/knowledge-bases/{kbId}/documents/{docId}", kbA.getId(), doc.getId())
                            .header("Authorization", "Bearer " + ownerBToken)
                            .header("X-Org-Id", orgB.getId()))
                    .andExpect(status().isNotFound());
        }
    }

    // ===== 5.8 RAGFlow 上传失败测试 =====
    @Nested
    @DisplayName("5.8 RAGFlow 上传失败")
    class RagFlowUploadFailureTests {
        @Test
        @DisplayName("RAGFlow 上传抛异常 → 返回 500")
        void upload_ragflowFails_returns500() throws Exception {
            when(ragFlowClient.uploadDocument(anyString(), anyString(), any(), anyString()))
                    .thenThrow(new RuntimeException("RAGFlow 连接超时"));

            MockMultipartFile file = createTestFile("test.pdf", "application/pdf");

            mockMvc.perform(multipart("/api/v1/knowledge-bases/{kbId}/documents", kbA.getId())
                            .file(file)
                            .header("Authorization", "Bearer " + memberAToken)
                            .header("X-Org-Id", orgA.getId()))
                    .andExpect(status().isInternalServerError())
                    .andExpect(jsonPath("$.code").value(500));
            // 注:事务回滚导致 DB 断言不可行,通过响应状态验证
        }
    }

    // ===== 5.9 RAGFlow 解析触发失败测试 =====
    @Nested
    @DisplayName("5.9 RAGFlow 解析触发失败")
    class RagFlowParseFailureTests {
        @Test
        @DisplayName("parseDocument 抛异常 → 返回 500")
        void upload_parseFails_returns500() throws Exception {
            doThrow(new RuntimeException("解析触发失败"))
                    .when(ragFlowClient).parseDocument(anyString(), anyString());

            MockMultipartFile file = createTestFile("test.pdf", "application/pdf");

            mockMvc.perform(multipart("/api/v1/knowledge-bases/{kbId}/documents", kbA.getId())
                            .file(file)
                            .header("Authorization", "Bearer " + memberAToken)
                            .header("X-Org-Id", orgA.getId()))
                    .andExpect(status().isInternalServerError())
                    .andExpect(jsonPath("$.code").value(500));
            // 注:事务回滚导致 DB 断言不可行,通过响应状态验证
        }
    }

    // ===== 5.10 状态查询 PARSING → FAILED 转换 =====
    @Nested
    @DisplayName("5.10 PARSING → FAILED 转换")
    class StatusTransitionTests {
        @Test
        @DisplayName("RAGFlow 返回失败 → 状态置 FAILED,接口返回 FAILED")
        void getById_ragflowFailed_updatesToFailed() throws Exception {
            Document doc = new Document();
            doc.setKb(kbA);
            doc.setOrg(orgA);
            doc.setName("parsing.pdf");
            doc.setSizeBytes(1024);
            doc.setStatus(DocumentStatus.PARSING);
            doc.setRagflowDocId("rf-doc-fail");
            doc = documentRepository.save(doc);

            // Mock RAGFlow 返回失败(run=4)
            when(ragFlowClient.getDocumentStatus(kbA.getRagflowDatasetId(), "rf-doc-fail"))
                    .thenReturn("4");

            mockMvc.perform(get("/api/v1/knowledge-bases/{kbId}/documents/{docId}", kbA.getId(), doc.getId())
                            .header("Authorization", "Bearer " + memberAToken)
                            .header("X-Org-Id", orgA.getId()))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.status").value("FAILED"));

            // 验证数据库中状态已更新
            Document updated = documentRepository.findById(doc.getId()).orElseThrow();
            org.junit.jupiter.api.Assertions.assertEquals(DocumentStatus.FAILED, updated.getStatus());
        }
    }

    // ===== 5.11 删除时 RAGFlow 失败测试 =====
    @Nested
    @DisplayName("5.11 删除时 RAGFlow 失败")
    class DeleteRagFlowFailureTests {
        @Test
        @DisplayName("deleteDocument 抛异常 → 返回 500")
        void delete_ragflowFails_returns500() throws Exception {
            Document doc = new Document();
            doc.setKb(kbA);
            doc.setOrg(orgA);
            doc.setName("to-delete.pdf");
            doc.setSizeBytes(1024);
            doc.setStatus(DocumentStatus.READY);
            doc.setRagflowDocId("rf-doc-del-fail");
            doc = documentRepository.save(doc);

            doThrow(new RuntimeException("RAGFlow 删除失败"))
                    .when(ragFlowClient).deleteDocument(anyString(), anyString());

            mockMvc.perform(delete("/api/v1/knowledge-bases/{kbId}/documents/{docId}", kbA.getId(), doc.getId())
                            .header("Authorization", "Bearer " + adminAToken)
                            .header("X-Org-Id", orgA.getId()))
                    .andExpect(status().isInternalServerError());
            // 注:事务回滚导致 DB 断言不可行,通过响应状态验证
        }
    }

    // ===== 5.12 列表不刷新测试 =====
    @Nested
    @DisplayName("5.12 列表不刷新")
    class ListNoRefreshTests {
        @Test
        @DisplayName("列表接口不触发 RAGFlow 查询,直接返回存储状态")
        void list_doesNotQueryRagFlow() throws Exception {
            // 创建 PARSING 状态文档
            Document doc = new Document();
            doc.setKb(kbA);
            doc.setOrg(orgA);
            doc.setName("parsing.pdf");
            doc.setSizeBytes(1024);
            doc.setStatus(DocumentStatus.PARSING);
            doc.setRagflowDocId("rf-doc-list");
            documentRepository.save(doc);

            mockMvc.perform(get("/api/v1/knowledge-bases/{kbId}/documents", kbA.getId())
                            .header("Authorization", "Bearer " + memberAToken)
                            .header("X-Org-Id", orgA.getId()))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.length()").value(1))
                    .andExpect(jsonPath("$.data[0].status").value("PARSING"));

            // 验证未调用 RAGFlow
            verify(ragFlowClient, never()).getDocumentStatus(anyString(), anyString());
        }
    }
}
