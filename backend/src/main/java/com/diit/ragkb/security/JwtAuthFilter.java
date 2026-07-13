package com.diit.ragkb.security;

import com.diit.ragkb.common.ApiResponse;
import com.diit.ragkb.model.Member;
import com.diit.ragkb.repository.MemberRepository;
import com.diit.ragkb.service.AuthService;
import com.diit.ragkb.service.JwtService;
import com.diit.ragkb.service.RedisService;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.jsonwebtoken.Claims;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpMethod;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.Collections;
import java.util.UUID;

/**
 * JWT 认证过滤器
 *
 * 三层安全检查:
 * 1. JWT 签名+有效期(JwtService)
 * 2. Redis jti 黑名单(改密后立即失效)
 * 3. token_version 比对(管理员重置后旧 token 全部失效)
 *
 * Redis 不可达时 fail-close(503)
 */
@Slf4j
@Component
public class JwtAuthFilter extends OncePerRequestFilter {

    private static final String HEADER_AUTH = "Authorization";
    private static final String HEADER_ORG = "X-Org-Id";
    private static final String BEARER_PREFIX = "Bearer ";

    private final JwtService jwtService;
    private final AuthService authService;
    private final RedisService redisService;
    private final MemberRepository memberRepository;
    private final ObjectMapper objectMapper;

    public JwtAuthFilter(JwtService jwtService,
                         AuthService authService,
                         RedisService redisService,
                         MemberRepository memberRepository,
                         ObjectMapper objectMapper) {
        this.jwtService = jwtService;
        this.authService = authService;
        this.redisService = redisService;
        this.memberRepository = memberRepository;
        this.objectMapper = objectMapper;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String path = request.getRequestURI();
        // 注册、登录和健康检查无需 JWT；其余端点均经过 JWT 校验。
        return path.equals("/api/v1/auth/register")
                || path.equals("/api/v1/auth/login")
                || path.equals("/actuator/health")
                || path.startsWith("/actuator/health/")
                || path.equals("/actuator/prometheus");
    }

    /** 是否是免租户上下文但需 JWT 的端点(如改密) */
    private boolean isAuthOnlyEndpoint(HttpServletRequest request) {
        return request.getRequestURI().equals("/api/v1/auth/change-password");
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        try {
            // 1. 解析 JWT
            String token = extractToken(request);
            if (token == null) {
                sendError(response, 401, "未携带有效认证凭证");
                return;
            }

            Claims claims = jwtService.parseToken(token);
            if (claims == null) {
                sendError(response, 401, "无效或已过期的 token");
                return;
            }

            String subject = claims.getSubject();
            String jti = claims.getId();
            Integer tvObj = claims.get("tv", Integer.class);
            int tv = (tvObj != null) ? tvObj : -1; // 缺失时必然不匹配任何用户的 tokenVersion(>=0)

            // 2. Redis 黑名单检查(fail-close)
            if (!redisService.isAvailable()) {
                sendError(response, 503, "认证服务不可用");
                return;
            }
            if (authService.isTokenBlacklisted(jti)) {
                sendError(response, 401, "token 已失效");
                return;
            }

            // 3. token_version 比对(管理员重置后旧 token 失效)
            UUID userId = UUID.fromString(subject);
            int currentTv = authService.getTokenVersion(userId);
            if (tv != currentTv) {
                sendError(response, 401, "token 已失效(密码已被重置)");
                return;
            }

            // 存储 JWT 信息供 Controller 使用(改密时需要 jti 和 remainingSeconds)
            request.setAttribute("jwtJti", jti);
            request.setAttribute("jwtRemainingSeconds", jwtService.getRemainingSeconds(claims));
            request.setAttribute("userId", userId);

            // 4. 免租户上下文端点(创建组织/改密):只需 JWT subject,不查 member
            if (isBootstrapEndpoint(request) || isAuthOnlyEndpoint(request)) {
                var authentication = new UsernamePasswordAuthenticationToken(
                        subject, null, Collections.emptyList());
                SecurityContextHolder.getContext().setAuthentication(authentication);
                request.setAttribute("subjectId", subject);
                filterChain.doFilter(request, response);
                return;
            }

            // 5. 目标组织 ID
            String orgIdHeader = request.getHeader(HEADER_ORG);
            UUID orgId;
            try {
                orgId = UUID.fromString(orgIdHeader);
            } catch (IllegalArgumentException | NullPointerException e) {
                sendError(response, 401, "缺少或非法的 X-Org-Id 请求头");
                return;
            }

            // 6. 服务端查 member(subject + orgId → role)
            Member member = memberRepository.findBySubjectIdAndOrgId(subject, orgId).orElse(null);
            if (member == null) {
                sendError(response, 401, "该主体在此组织无成员身份");
                return;
            }

            // 7. 设置租户上下文
            TenantContext.set(member.getOrg().getId(), member.getId(), member.getRole().name());

            // 8. 设置 Spring Security Authentication
            var authorities = Collections.singletonList(
                    new SimpleGrantedAuthority("ROLE_" + member.getRole().name()));
            var authentication = new UsernamePasswordAuthenticationToken(
                    subject, null, authorities);
            SecurityContextHolder.getContext().setAuthentication(authentication);

            filterChain.doFilter(request, response);
        } finally {
            TenantContext.clear();
            SecurityContextHolder.clearContext();
        }
    }

    private boolean isBootstrapEndpoint(HttpServletRequest request) {
        return HttpMethod.POST.matches(request.getMethod())
                && request.getRequestURI().equals("/api/v1/organizations");
    }

    private String extractToken(HttpServletRequest request) {
        String header = request.getHeader(HEADER_AUTH);
        if (header == null || !header.startsWith(BEARER_PREFIX)) {
            return null;
        }
        return header.substring(BEARER_PREFIX.length());
    }

    private void sendError(HttpServletResponse response, int status, String message) throws IOException {
        response.setStatus(status);
        response.setContentType("application/json;charset=UTF-8");
        response.getWriter().write(objectMapper.writeValueAsString(ApiResponse.fail(status, message)));
    }
}
