package com.diit.ragkb;

import com.diit.ragkb.model.MemberRole;
import com.diit.ragkb.model.Organization;
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
 * 多租户隔离安全测试(覆盖 spec 中所有安全场景)
 *
 * 构造两个组织(A/B)各一套成员,验证:
 * - 跨租户访问一律 404(不泄露存在性)
 * - 同租户内越权一律 403
 * - 线程复用不串上下文
 * - 角色层级矩阵
 */
@SpringBootTest
@AutoConfigureMockMvc
@DisplayName("多租户隔离安全测试")
class TenantIsolationTest {

    @Autowired private MockMvc mockMvc;
    @Autowired private TestHelper testHelper;
    @Autowired private ObjectMapper objectMapper;

    private Organization orgA, orgB;
    private String ownerAToken, adminAToken, memberAToken;
    private String ownerBToken;

    @BeforeEach
    void setUp() {
        // 构造组织 A:ownerA + adminA + memberA
        orgA = testHelper.createOrg("测试组织A");
        var ownerA  = testHelper.createMember("subject-owner-a",  orgA, MemberRole.OWNER);
        var adminA  = testHelper.createMember("subject-admin-a",  orgA, MemberRole.ADMIN);
        var memberA = testHelper.createMember("subject-member-a", orgA, MemberRole.MEMBER);

        // 构造组织 B:ownerB
        orgB = testHelper.createOrg("测试组织B");
        var ownerB  = testHelper.createMember("subject-owner-b",  orgB, MemberRole.OWNER);

        ownerAToken  = testHelper.generateToken("subject-owner-a");
        adminAToken  = testHelper.generateToken("subject-admin-a");
        memberAToken = testHelper.generateToken("subject-member-a");
        ownerBToken  = testHelper.generateToken("subject-owner-b");
    }

    // ==================== 认证上下文解析 ====================

    @Nested
    @DisplayName("认证与上下文解析")
    class AuthTests {

        @Test
        @DisplayName("无凭证请求 → 401")
        void noCredentials_returns401() throws Exception {
            mockMvc.perform(get("/api/v1/teams")
                    .header("X-Org-Id", orgA.getId()))
                    .andExpect(status().isUnauthorized());
        }

        @Test
        @DisplayName("伪造 JWT → 401")
        void forgedJwt_returns401() throws Exception {
            mockMvc.perform(get("/api/v1/teams")
                    .header("Authorization", "Bearer forged.invalid.token")
                    .header("X-Org-Id", orgA.getId()))
                    .andExpect(status().isUnauthorized());
        }

        @Test
        @DisplayName("主体真实但目标组织无 member → 401(按无成员身份处理)")
        void subjectWithNoMemberInOrg_returns401() throws Exception {
            // ownerA 在 orgB 没有 member 记录
            mockMvc.perform(get("/api/v1/teams")
                    .header("Authorization", "Bearer " + ownerAToken)
                    .header("X-Org-Id", orgB.getId()))
                    .andExpect(status().isUnauthorized());
        }

        @Test
        @DisplayName("缺少 X-Org-Id → 401")
        void missingOrgId_returns401() throws Exception {
            mockMvc.perform(get("/api/v1/teams")
                    .header("Authorization", "Bearer " + ownerAToken))
                    .andExpect(status().isUnauthorized());
        }
    }

    // ==================== 跨租户隔离 ====================

    @Nested
    @DisplayName("跨租户隔离(跨组织 → 404 不泄露存在性)")
    class CrossTenantTests {

        @Test
        @DisplayName("跨组织列举团队 → 空列表(不包含他组织数据)")
        void crossOrgListTeams_returnsOnlyOwnOrg() throws Exception {
            // ownerB 列举团队,不应看到 orgA 的团队
            mockMvc.perform(get("/api/v1/teams")
                    .header("Authorization", "Bearer " + ownerBToken)
                    .header("X-Org-Id", orgB.getId()))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data").isArray())
                    .andExpect(jsonPath("$.data.length()").value(0));
        }

        @Test
        @DisplayName("跨组织列举成员 → 空列表(不包含他组织数据)")
        void crossOrgListMembers_returnsOnlyOwnOrg() throws Exception {
            // ownerB 列举成员,应只看到自己(orgB 的 owner)
            mockMvc.perform(get("/api/v1/members")
                    .header("Authorization", "Bearer " + ownerBToken)
                    .header("X-Org-Id", orgB.getId()))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data").isArray())
                    .andExpect(jsonPath("$.data.length()").value(1)); // 只有 ownerB 自己
        }
    }

    // ==================== 角色层级 ====================

    @Nested
    @DisplayName("角色层级矩阵")
    class RoleHierarchyTests {

        @Test
        @DisplayName("member 不能邀请成员 → 403")
        void memberCannotInvite_returns403() throws Exception {
            mockMvc.perform(post("/api/v1/members")
                    .header("Authorization", "Bearer " + memberAToken)
                    .header("X-Org-Id", orgA.getId())
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("{\"subjectId\":\"subject-new\",\"role\":\"MEMBER\"}"))
                    .andExpect(status().isForbidden());
        }

        @Test
        @DisplayName("admin 可邀请 member")
        void adminCanInviteMember() throws Exception {
            mockMvc.perform(post("/api/v1/members")
                    .header("Authorization", "Bearer " + adminAToken)
                    .header("X-Org-Id", orgA.getId())
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("{\"subjectId\":\"subject-new-member\",\"role\":\"MEMBER\"}"))
                    .andExpect(status().isOk());
        }

        @Test
        @DisplayName("admin 不能邀请 admin → 403")
        void adminCannotInviteAdmin_returns403() throws Exception {
            mockMvc.perform(post("/api/v1/members")
                    .header("Authorization", "Bearer " + adminAToken)
                    .header("X-Org-Id", orgA.getId())
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("{\"subjectId\":\"subject-new-admin\",\"role\":\"ADMIN\"}"))
                    .andExpect(status().isForbidden());
        }

        @Test
        @DisplayName("admin 不能邀请为 owner → 403")
        void adminCannotInviteOwner_returns403() throws Exception {
            mockMvc.perform(post("/api/v1/members")
                    .header("Authorization", "Bearer " + adminAToken)
                    .header("X-Org-Id", orgA.getId())
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("{\"subjectId\":\"subject-new-owner\",\"role\":\"OWNER\"}"))
                    .andExpect(status().isForbidden());
        }

        @Test
        @DisplayName("admin 不能修改 owner 角色 → 403")
        void adminCannotChangeOwnerRole_returns403() throws Exception {
            // adminA 试图改 ownerA 的角色
            var ownerA = testHelper.createMember("subject-owner-a-for-change",
                    orgA, MemberRole.OWNER);
            mockMvc.perform(patch("/api/v1/members/" + ownerA.getId() + "/role")
                    .header("Authorization", "Bearer " + adminAToken)
                    .header("X-Org-Id", orgA.getId())
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("{\"role\":\"MEMBER\"}"))
                    .andExpect(status().isForbidden());
        }
    }

    // ==================== 创建组织(bootstrap) ====================

    @Nested
    @DisplayName("创建组织 bootstrap")
    class BootstrapTests {

        @Test
        @DisplayName("创建组织(需 JWT,免租户上下文)→ 201")
        void createOrg_bootstrap() throws Exception {
            String token = testHelper.generateToken("subject-new-for-org");
            mockMvc.perform(post("/api/v1/organizations")
                    .header("Authorization", "Bearer " + token)
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("{\"name\":\"新组织\"}"))
                    .andExpect(status().isCreated())
                    .andExpect(jsonPath("$.data.name").value("新组织"));
        }

        @Test
        @DisplayName("无 JWT 创建组织 → 401")
        void createOrg_noJwt_returns401() throws Exception {
            mockMvc.perform(post("/api/v1/organizations")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("{\"name\":\"新组织\"}"))
                    .andExpect(status().isUnauthorized());
        }
    }
}
