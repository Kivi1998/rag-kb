package com.diit.ragkb.controller;

import com.diit.ragkb.common.ApiResponse;
import com.diit.ragkb.security.TenantContext;
import com.diit.ragkb.service.AuthService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

import java.util.Map;
import java.util.UUID;

/**
 * 认证控制器:注册/登录/改密
 */
@RestController
@RequestMapping("/api/v1/auth")
@RequiredArgsConstructor
public class AuthController {

    private final AuthService authService;

    /**
     * 注册(免认证)
     */
    @PostMapping("/register")
    @ResponseStatus(HttpStatus.CREATED)
    public ApiResponse<Map<String, Object>> register(@Valid @RequestBody RegisterRequest req) {
        return ApiResponse.ok(authService.register(req.getEmail(), req.getPassword(), req.getDisplayName()));
    }

    /**
     * 登录(免认证)
     */
    @PostMapping("/login")
    public ApiResponse<Map<String, Object>> login(@Valid @RequestBody LoginRequest req) {
        return ApiResponse.ok(authService.login(req.getEmail(), req.getPassword()));
    }

    /**
     * 修改密码(需认证)
     */
    @PostMapping("/change-password")
    public ApiResponse<Void> changePassword(HttpServletRequest request,
                                            @Valid @RequestBody ChangePasswordRequest req) {
        UUID userId = extractUserId(request);
        // 修改密码后将当前 JWT jti 加入黑名单
        String jti = (String) request.getAttribute("jwtJti");
        long remainingSeconds = (long) request.getAttribute("jwtRemainingSeconds");

        authService.changePassword(userId, req.getOldPassword(), req.getNewPassword());
        authService.blacklistToken(jti, remainingSeconds);

        return ApiResponse.ok();
    }

    /** 从 request attribute 获取 userId(由 JwtAuthFilter 设置) */
    private UUID extractUserId(HttpServletRequest request) {
        Object userId = request.getAttribute("userId");
        if (userId instanceof UUID) return (UUID) userId;
        // fallback:从 TenantContext 获取
        UUID memberId = TenantContext.getMemberId();
        if (memberId != null) return memberId;
        throw new IllegalStateException("无法获取当前用户 ID");
    }

    @Data
    public static class RegisterRequest {
        @NotBlank(message = "邮箱不能为空")
        @Email(message = "邮箱格式不正确")
        private String email;
        @NotBlank(message = "密码不能为空")
        @Size(min = 8, message = "密码至少 8 位")
        private String password;
        private String displayName;
    }

    @Data
    public static class LoginRequest {
        @NotBlank(message = "邮箱不能为空")
        private String email;
        @NotBlank(message = "密码不能为空")
        private String password;
    }

    @Data
    public static class ChangePasswordRequest {
        @NotBlank(message = "旧密码不能为空")
        private String oldPassword;
        @NotBlank(message = "新密码不能为空")
        @Size(min = 8, message = "新密码至少 8 位")
        private String newPassword;
    }
}
