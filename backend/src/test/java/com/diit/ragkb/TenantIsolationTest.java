package com.diit.ragkb;

import com.diit.ragkb.model.MemberRole;
import com.diit.ragkb.model.Organization;
import com.diit.ragkb.model.User;
import com.diit.ragkb.repository.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * 多租户隔离安全测试
 */
@SpringBootTest
@AutoConfigureMockMvc
@DisplayName("多租户隔离安全测试")
class TenantIsolationTest {

    @Autowired private MockMvc mockMvc;
    @Autowired private TestHelper testHelper;
    @Autowired private ObjectMapper objectMapper;
    @Autowired private MemberRepository memberRepository;
    @Autowired private OrganizationRepository organizationRepository;
    @Autowired private KnowledgeBaseRepository knowledgeBaseRepository;
    @Autowired private UserRepository userRepository;

    private Organization orgA, orgB;
    private User userOwnerA, userAdminA, userMemberA, userOwnerB;
    private String ownerAToken, adminAToken, memberAToken, ownerBToken;

    @BeforeEach
    void setUp() {
        // 清理数据(防唯一约束冲突)
        knowledgeBaseRepository.deleteAll();
        memberRepository.deleteAll();
        organizationRepository.deleteAll();
        userRepository.deleteAll();

        // 创建用户
        userOwnerA  = testHelper.createUser("owner-a@test.com",  "Pass1234!", "Owner A");
        userAdminA  = testHelper.createUser("admin-a@test.com",  "Pass1234!", "Admin A");
        userMemberA = testHelper.createUser("member-a@test.com", "Pass1234!", "Member A");
        userOwnerB  = testHelper.createUser("owner-b@test.com",  "Pass1234!", "Owner B");

        // 创建组织
        orgA = testHelper.createOrg("测试组织A");
        orgB = testHelper.createOrg("测试组织B");

        // 创建成员(userId 作为 subjectId)
        testHelper.createMember(userOwnerA.getId().toString(),  orgA, MemberRole.OWNER);
        testHelper.createMember(userAdminA.getId().toString(),  orgA, MemberRole.ADMIN);
        testHelper.createMember(userMemberA.getId().toString(), orgA, MemberRole.MEMBER);
        testHelper.createMember(userOwnerB.getId().toString(),  orgB, MemberRole.OWNER);

        // 生成 JWT
        ownerAToken  = testHelper.generateToken(userOwnerA.getId(), 0);
        adminAToken  = testHelper.generateToken(userAdminA.getId(), 0);
        memberAToken = testHelper.generateToken(userMemberA.getId(), 0);
        ownerBToken  = testHelper.generateToken(userOwnerB.getId(), 0);
    }

    @Nested
    @DisplayName("认证与上下文解析")
    class AuthTests {
        @Test @DisplayName("健康检查无需凭证")
        void healthCheck_isPublic() throws Exception {
            mockMvc.perform(get("/actuator/health"))
                    .andExpect(status().isOk());
        }

        @Test @DisplayName("无凭证请求 → 401")
        void noCredentials_returns401() throws Exception {
            mockMvc.perform(get("/api/v1/teams").header("X-Org-Id", orgA.getId()))
                    .andExpect(status().isUnauthorized());
        }

        @Test @DisplayName("伪造 JWT → 401")
        void forgedJwt_returns401() throws Exception {
            mockMvc.perform(get("/api/v1/teams")
                    .header("Authorization", "Bearer forged.invalid.token")
                    .header("X-Org-Id", orgA.getId()))
                    .andExpect(status().isUnauthorized());
        }

        @Test @DisplayName("主体真实但目标组织无 member → 401")
        void subjectWithNoMemberInOrg_returns401() throws Exception {
            mockMvc.perform(get("/api/v1/teams")
                    .header("Authorization", "Bearer " + ownerAToken)
                    .header("X-Org-Id", orgB.getId()))
                    .andExpect(status().isUnauthorized());
        }

        @Test @DisplayName("缺少 X-Org-Id → 401")
        void missingOrgId_returns401() throws Exception {
            mockMvc.perform(get("/api/v1/teams")
                    .header("Authorization", "Bearer " + ownerAToken))
                    .andExpect(status().isUnauthorized());
        }
    }

    @Nested
    @DisplayName("跨租户隔离")
    class CrossTenantTests {
        @Test @DisplayName("跨组织列举团队 → 空列表")
        void crossOrgListTeams_returnsOnlyOwnOrg() throws Exception {
            mockMvc.perform(get("/api/v1/teams")
                    .header("Authorization", "Bearer " + ownerBToken)
                    .header("X-Org-Id", orgB.getId()))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.length()").value(0));
        }

        @Test @DisplayName("跨组织列举成员 → 只有本组织")
        void crossOrgListMembers_returnsOnlyOwnOrg() throws Exception {
            mockMvc.perform(get("/api/v1/members")
                    .header("Authorization", "Bearer " + ownerBToken)
                    .header("X-Org-Id", orgB.getId()))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.length()").value(1));
        }
    }

    @Nested
    @DisplayName("角色层级矩阵")
    class RoleHierarchyTests {
        @Test @DisplayName("member 不能邀请 → 403")
        void memberCannotInvite_returns403() throws Exception {
            mockMvc.perform(post("/api/v1/members")
                    .header("Authorization", "Bearer " + memberAToken)
                    .header("X-Org-Id", orgA.getId())
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("{\"subjectId\":\"xxx\",\"role\":\"MEMBER\"}"))
                    .andExpect(status().isForbidden());
        }

        @Test @DisplayName("admin 可邀请 member")
        void adminCanInviteMember() throws Exception {
            User newUser = testHelper.createUser("new@test.com", "Pass1234!", "New");
            mockMvc.perform(post("/api/v1/members")
                    .header("Authorization", "Bearer " + adminAToken)
                    .header("X-Org-Id", orgA.getId())
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("{\"subjectId\":\"" + newUser.getId() + "\",\"role\":\"MEMBER\"}"))
                    .andExpect(status().isOk());
        }

        @Test @DisplayName("admin 不能邀请 admin → 403")
        void adminCannotInviteAdmin_returns403() throws Exception {
            mockMvc.perform(post("/api/v1/members")
                    .header("Authorization", "Bearer " + adminAToken)
                    .header("X-Org-Id", orgA.getId())
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("{\"subjectId\":\"xxx\",\"role\":\"ADMIN\"}"))
                    .andExpect(status().isForbidden());
        }

        @Test @DisplayName("admin 不能邀请 owner → 403")
        void adminCannotInviteOwner_returns403() throws Exception {
            mockMvc.perform(post("/api/v1/members")
                    .header("Authorization", "Bearer " + adminAToken)
                    .header("X-Org-Id", orgA.getId())
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("{\"subjectId\":\"xxx\",\"role\":\"OWNER\"}"))
                    .andExpect(status().isForbidden());
        }

        @Test @DisplayName("admin 不能修改 owner 角色 → 403")
        void adminCannotChangeOwnerRole_returns403() throws Exception {
            var ownerA = testHelper.createMember("extra-owner", orgA, MemberRole.OWNER);
            mockMvc.perform(patch("/api/v1/members/" + ownerA.getId() + "/role")
                    .header("Authorization", "Bearer " + adminAToken)
                    .header("X-Org-Id", orgA.getId())
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("{\"role\":\"MEMBER\"}"))
                    .andExpect(status().isForbidden());
        }
    }

    @Nested
    @DisplayName("创建组织 bootstrap")
    class BootstrapTests {
        @Test @DisplayName("有 JWT 创建组织 → 201")
        void createOrg_bootstrap() throws Exception {
            User newUser = testHelper.createUser("bootstrap@test.com", "Pass1234!", "Bootstrap");
            String token = testHelper.generateToken(newUser.getId(), 0);
            mockMvc.perform(post("/api/v1/organizations")
                    .header("Authorization", "Bearer " + token)
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("{\"name\":\"新组织\"}"))
                    .andExpect(status().isCreated())
                    .andExpect(jsonPath("$.data.name").value("新组织"));
        }

        @Test @DisplayName("无 JWT 创建组织 → 401")
        void createOrg_noJwt_returns401() throws Exception {
            mockMvc.perform(post("/api/v1/organizations")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("{\"name\":\"新组织\"}"))
                    .andExpect(status().isUnauthorized());
        }

        @Test @DisplayName("组织路径的前缀变体不能绕过租户上下文")
        void organizationPathVariant_requiresOrgContext() throws Exception {
            User newUser = testHelper.createUser("bootstrap-path@test.com", "Pass1234!", "Bootstrap Path");
            String token = testHelper.generateToken(newUser.getId(), 0);

            mockMvc.perform(post("/api/v1/organizations/unexpected")
                    .header("Authorization", "Bearer " + token)
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("{\"name\":\"不应创建\"}"))
                    .andExpect(status().isUnauthorized());
        }
    }
}
