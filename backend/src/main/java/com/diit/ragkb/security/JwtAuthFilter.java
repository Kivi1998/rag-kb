package com.diit.ragkb.security;

import com.diit.ragkb.common.ApiResponse;
import com.diit.ragkb.exception.UnauthenticatedException;
import com.diit.ragkb.model.Member;
import com.diit.ragkb.repository.MemberRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpMethod;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.util.Collections;

import javax.crypto.SecretKey;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.UUID;

/**
 * 最小认证占位过滤器
 *
 * 流程:
 * 1. 从 Authorization: Bearer <token> 解析 JWT,取出 subject(sub claim)
 * 2. 从请求头 X-Org-Id 取目标组织 ID(不是自报归属,是"我要访问哪个组织")
 * 3. 服务端用 (subject, orgId) 查 member 表得出真实 org_id 与 role → 不采信客户端自报
 * 4. 设置 TenantContext(请求结束在 finally 清理)
 *
 * 免租户上下文的端点(如创建组织)由 SecurityConfig 白名单跳过此过滤器
 */
@Slf4j
@Component
public class JwtAuthFilter extends OncePerRequestFilter {

    private static final String HEADER_AUTH = "Authorization";
    private static final String HEADER_ORG = "X-Org-Id";
    private static final String BEARER_PREFIX = "Bearer ";

    /**
     * 创建组织端点:跳过 member 查询,但仍解析 JWT subject
     * 通过 URI 前缀判断,避免 context-path 影响(getRequestURI→getServletPath)
     */
    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return false; // 所有请求都经过此过滤器
    }

    /** 是否是 bootstrap 端点(免租户上下文,只需 subject) */
    private boolean isBootstrapEndpoint(HttpServletRequest request) {
        return HttpMethod.POST.matches(request.getMethod())
                && request.getRequestURI().contains("/api/v1/organizations");
    }

    private final MemberRepository memberRepository;
    private final SecretKey signingKey;
    private final ObjectMapper objectMapper;

    public JwtAuthFilter(MemberRepository memberRepository,
                         @Value("${spring.security.jwt.secret}") String jwtSecret,
                         ObjectMapper objectMapper) {
        this.memberRepository = memberRepository;
        this.signingKey = Keys.hmacShaKeyFor(jwtSecret.getBytes(StandardCharsets.UTF_8));
        this.objectMapper = objectMapper;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        try {
            // 1. 解析 JWT subject(所有端点都需要)
            String subject = extractSubject(request);
            if (subject == null) {
                sendError(response, 401, "未携带有效认证凭证");
                return;
            }

            // 2. bootstrap 端点:只需 subject,不查 member/不设租户上下文
            if (isBootstrapEndpoint(request)) {
                var authentication = new UsernamePasswordAuthenticationToken(
                        subject, null, Collections.emptyList());
                SecurityContextHolder.getContext().setAuthentication(authentication);
                // 将 subject 注入 request attribute,供 Controller 使用
                request.setAttribute("subjectId", subject);
                filterChain.doFilter(request, response);
                return;
            }

            // 3. 目标组织 ID(来自请求头,表示"我要访问哪个组织的资源")
            String orgIdHeader = request.getHeader(HEADER_ORG);
            UUID orgId;
            try {
                orgId = UUID.fromString(orgIdHeader);
            } catch (IllegalArgumentException | NullPointerException e) {
                sendError(response, 401, "缺少或非法的 X-Org-Id 请求头");
                return;
            }

            // 4. 服务端查 member 表:subject + orgId → 真实 role(铁律:不采信客户端自报)
            Member member = memberRepository.findBySubjectIdAndOrgId(subject, orgId)
                    .orElse(null);
            if (member == null) {
                sendError(response, 401, "该主体在此组织无成员身份");
                return;
            }

            // 5. 设置租户上下文
            TenantContext.set(member.getOrg().getId(), member.getId(), member.getRole().name());

            // 6. 设置 Spring Security Authentication(让 authenticated() 检查通过)
            var authorities = Collections.singletonList(
                    new SimpleGrantedAuthority("ROLE_" + member.getRole().name()));
            var authentication = new UsernamePasswordAuthenticationToken(
                    subject, null, authorities);
            SecurityContextHolder.getContext().setAuthentication(authentication);

            filterChain.doFilter(request, response);
        } finally {
            // 6. 无条件清理(防线程复用串租户)
            TenantContext.clear();
            SecurityContextHolder.clearContext();
        }
    }

    /** 在 filter 层直接返回 401 JSON(绕过 DispatcherServlet,GlobalExceptionHandler 无法捕获) */
    private void sendError(HttpServletResponse response, int status, String message) throws IOException {
        response.setStatus(status);
        response.setContentType("application/json;charset=UTF-8");
        response.getWriter().write(objectMapper.writeValueAsString(ApiResponse.fail(status, message)));
    }

    /**
     * 从 Authorization 头解析 JWT sub claim
     * 占位方案:对齐未来 OIDC 的 sub 字段
     */
    private String extractSubject(HttpServletRequest request) {
        String header = request.getHeader(HEADER_AUTH);
        if (header == null || !header.startsWith(BEARER_PREFIX)) {
            return null;
        }
        String token = header.substring(BEARER_PREFIX.length());
        try {
            Claims claims = Jwts.parser()
                    .verifyWith(signingKey)
                    .build()
                    .parseSignedClaims(token)
                    .getPayload();
            return claims.getSubject();
        } catch (JwtException e) {
            log.warn("JWT 解析失败: {}", e.getMessage());
            return null;
        }
    }
}
