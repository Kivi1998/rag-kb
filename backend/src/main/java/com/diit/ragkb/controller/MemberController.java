package com.diit.ragkb.controller;

import com.diit.ragkb.common.ApiResponse;
import com.diit.ragkb.model.Member;
import com.diit.ragkb.model.MemberRole;
import com.diit.ragkb.security.TenantContext;
import com.diit.ragkb.service.AuthService;
import com.diit.ragkb.service.MemberService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

/**
 * 成员控制器(需认证+租户上下文)
 */
@RestController
@RequestMapping("/api/v1/members")
@RequiredArgsConstructor
public class MemberController {

    private final MemberService memberService;
    private final AuthService authService;

    @PostMapping
    public ApiResponse<Member> invite(@Valid @RequestBody InviteMemberRequest req) {
        return ApiResponse.ok(memberService.invite(req.getSubjectId(), req.getRole()));
    }

    @GetMapping
    public ApiResponse<List<Member>> list() {
        return ApiResponse.ok(memberService.listByCurrentOrg());
    }

    @GetMapping("/{id}")
    public ApiResponse<Member> getById(@PathVariable("id") UUID id) {
        return ApiResponse.ok(memberService.getByIdAndCurrentOrg(id));
    }

    @PatchMapping("/{id}/role")
    public ApiResponse<Member> changeRole(@PathVariable("id") UUID id,
                                          @Valid @RequestBody ChangeRoleRequest req) {
        return ApiResponse.ok(memberService.changeRole(id, req.getRole()));
    }

    /**
     * 管理员重置成员密码(仅 owner/admin)
     */
    @PostMapping("/{id}/reset-password")
    public ApiResponse<String> resetPassword(@PathVariable("id") UUID memberId) {
        String callerRole = TenantContext.getRole();
        String tempPassword = authService.adminResetPassword(
                TenantContext.getMemberId(), memberId, callerRole);
        return ApiResponse.ok(tempPassword);
    }

    @Data
    public static class InviteMemberRequest {
        @NotBlank(message = "subjectId 不能为空")
        private String subjectId;
        @NotNull(message = "角色不能为空")
        private MemberRole role;
    }

    @Data
    public static class ChangeRoleRequest {
        @NotNull(message = "新角色不能为空")
        private MemberRole role;
    }
}
