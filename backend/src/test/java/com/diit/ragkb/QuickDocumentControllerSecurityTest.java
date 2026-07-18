package com.diit.ragkb;

import com.diit.ragkb.model.KnowledgeBase;
import com.diit.ragkb.model.Member;
import com.diit.ragkb.model.MemberRole;
import com.diit.ragkb.model.Organization;
import com.diit.ragkb.model.User;
import com.diit.ragkb.repository.ChatSessionRepository;
import com.diit.ragkb.repository.KnowledgeBaseRepository;
import com.diit.ragkb.repository.MemberRepository;
import com.diit.ragkb.repository.OrganizationRepository;
import com.diit.ragkb.repository.UserRepository;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.web.servlet.MockMvc;

import java.util.UUID;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 会话内临时文档端点的跨租户隔离：另一个组织即使拿到真实 sessionId 也不能访问。
 *
 * <p>测试专用 {@code application.yml}（{@code src/test/resources/}）是整体覆盖主配置，不是
 * 合并——{@code rag.quick-document.enabled} 默认值 {@code true} 只在主配置里，测试环境不会
 * 自动继承，必须显式声明，否则 {@code @ConditionalOnProperty} 在属性完全缺失时判定为不满足，
 * {@code QuickDocumentController} 不会被注册，请求会掉进静态资源兜底变成 404/500。</p>
 */
@SpringBootTest(properties = "rag.quick-document.enabled=true")
@AutoConfigureMockMvc
@DisplayName("临时文档跨租户隔离")
class QuickDocumentControllerSecurityTest {

    @Autowired private MockMvc mockMvc;
    @Autowired private TestHelper testHelper;
    @Autowired private OrganizationRepository organizationRepository;
    @Autowired private MemberRepository memberRepository;
    @Autowired private UserRepository userRepository;
    @Autowired private KnowledgeBaseRepository knowledgeBaseRepository;
    @Autowired private ChatSessionRepository chatSessionRepository;
    @Autowired private ObjectMapper objectMapper;

    private Organization orgA;
    private Organization orgB;
    private KnowledgeBase kbA;
    private String ownerAToken;
    private String ownerBToken;
    private UUID sessionIdInOrgA;

    @BeforeEach
    void setUp() throws Exception {
        chatSessionRepository.deleteAll();
        knowledgeBaseRepository.deleteAll();
        memberRepository.deleteAll();
        organizationRepository.deleteAll();
        userRepository.deleteAll();

        orgA = testHelper.createOrg("临时文档组织A");
        orgB = testHelper.createOrg("临时文档组织B");
        User userA = testHelper.createUser("quickdoc-a@test.com", "Pass1234!", "A");
        User userB = testHelper.createUser("quickdoc-b@test.com", "Pass1234!", "B");
        Member ownerA = testHelper.createMember(userA.getId().toString(), orgA, MemberRole.OWNER);
        testHelper.createMember(userB.getId().toString(), orgB, MemberRole.OWNER);
        ownerAToken = testHelper.generateToken(userA.getId(), 0);
        ownerBToken = testHelper.generateToken(userB.getId(), 0);

        kbA = new KnowledgeBase();
        kbA.setOrg(orgA);
        kbA.setName("知识库A");
        kbA.setCreatedBy(ownerA);
        kbA = knowledgeBaseRepository.save(kbA);

        String createSessionResponse = mockMvc.perform(post("/api/v1/knowledge-bases/" + kbA.getId() + "/sessions")
                        .header("Authorization", "Bearer " + ownerAToken)
                        .header("X-Org-Id", orgA.getId()))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();
        JsonNode node = objectMapper.readTree(createSessionResponse);
        sessionIdInOrgA = UUID.fromString(node.get("data").get("sessionId").asText());
    }

    @Test
    @DisplayName("跨组织上传临时文档 → 404")
    void crossOrgUpload_returns404() throws Exception {
        mockMvc.perform(multipart("/api/v1/knowledge-bases/" + kbA.getId() + "/sessions/" + sessionIdInOrgA
                        + "/quick-documents")
                        .file(new MockMultipartFile("file", "笔记.md", "text/markdown", "正文".getBytes()))
                        .header("Authorization", "Bearer " + ownerBToken)
                        .header("X-Org-Id", orgB.getId()))
                .andExpect(status().isNotFound());
    }

    @Test
    @DisplayName("跨组织查询临时文档列表 → 404")
    void crossOrgList_returns404() throws Exception {
        mockMvc.perform(get("/api/v1/knowledge-bases/" + kbA.getId() + "/sessions/" + sessionIdInOrgA
                        + "/quick-documents")
                        .header("Authorization", "Bearer " + ownerBToken)
                        .header("X-Org-Id", orgB.getId()))
                .andExpect(status().isNotFound());
    }

    @Test
    @DisplayName("跨组织删除临时文档 → 404")
    void crossOrgDelete_returns404() throws Exception {
        mockMvc.perform(delete("/api/v1/knowledge-bases/" + kbA.getId() + "/sessions/" + sessionIdInOrgA
                        + "/quick-documents/" + UUID.randomUUID())
                        .header("Authorization", "Bearer " + ownerBToken)
                        .header("X-Org-Id", orgB.getId()))
                .andExpect(status().isNotFound());
    }

    @Test
    @DisplayName("本组织正常上传临时文档 → 200")
    void ownOrgUpload_succeeds() throws Exception {
        mockMvc.perform(multipart("/api/v1/knowledge-bases/" + kbA.getId() + "/sessions/" + sessionIdInOrgA
                        + "/quick-documents")
                        .file(new MockMultipartFile("file", "笔记.md", "text/markdown", "# 标题\n正文".getBytes()))
                        .header("Authorization", "Bearer " + ownerAToken)
                        .header("X-Org-Id", orgA.getId()))
                .andExpect(status().isOk());
    }
}
