package com.diit.ragkb.security;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/** 使用独立静态密钥保护 Prometheus 拉取端点，避免依赖会过期的用户 JWT。 */
@Component
public class MetricsAuthFilter extends OncePerRequestFilter {

    private static final String METRICS_PATH = "/actuator/prometheus";
    private static final String TOKEN_HEADER = "X-Metrics-Key";

    @Value("${rag.observability.metrics-token:}")
    private String configuredToken;

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return !request.getRequestURI().equals(METRICS_PATH);
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        String provided = request.getHeader(TOKEN_HEADER);
        if (configuredToken == null || configuredToken.isBlank()) {
            response.sendError(HttpServletResponse.SC_SERVICE_UNAVAILABLE, "监控端点未配置访问密钥");
            return;
        }
        if (provided == null || !MessageDigest.isEqual(configuredToken.getBytes(StandardCharsets.UTF_8),
                provided.getBytes(StandardCharsets.UTF_8))) {
            response.sendError(HttpServletResponse.SC_UNAUTHORIZED, "监控访问密钥无效");
            return;
        }
        filterChain.doFilter(request, response);
    }
}
