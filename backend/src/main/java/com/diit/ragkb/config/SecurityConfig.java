package com.diit.ragkb.config;

import com.diit.ragkb.security.JwtAuthFilter;
import com.diit.ragkb.security.MetricsAuthFilter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

/**
 * Spring Security 配置
 *
 * URL 权限规则:
 * - POST /api/v1/organizations → 需有效 JWT、免租户上下文
 * - /actuator/health → permitAll（供编排平台探活）
 * - 其他 → 认证(经 JwtAuthFilter)
 */
@Configuration
@EnableWebSecurity
public class SecurityConfig {

    private final JwtAuthFilter jwtAuthFilter;
    private final MetricsAuthFilter metricsAuthFilter;

    public SecurityConfig(JwtAuthFilter jwtAuthFilter, MetricsAuthFilter metricsAuthFilter) {
        this.jwtAuthFilter = jwtAuthFilter;
        this.metricsAuthFilter = metricsAuthFilter;
    }

    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http
            .csrf(AbstractHttpConfigurer::disable)
            .sessionManagement(sm -> sm.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(auth -> auth
                // 免认证端点
                .requestMatchers("/api/v1/auth/register").permitAll()
                .requestMatchers("/api/v1/auth/login").permitAll()
                .requestMatchers("/actuator/health", "/actuator/health/**").permitAll()
                .requestMatchers("/actuator/prometheus").permitAll()
                // 其他一律需要认证
                .anyRequest().authenticated()
            )
            .addFilterBefore(metricsAuthFilter, UsernamePasswordAuthenticationFilter.class)
            .addFilterAfter(jwtAuthFilter, MetricsAuthFilter.class);

        return http.build();
    }
}
