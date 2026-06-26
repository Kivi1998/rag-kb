package com.diit.ragkb.config;

import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;

/**
 * RestTemplate 配置
 * RAGFlow 客户端专用,注入 API Key 认证
 */
@Configuration
public class RestTemplateConfig {

    @Bean
    public RestTemplate ragFlowRestTemplate(RagFlowProperties properties) {
        return new RestTemplateBuilder()
                .defaultHeader("Authorization", "Bearer " + properties.getApiKey())
                .setConnectTimeout(Duration.ofSeconds(10))
                .setReadTimeout(Duration.ofSeconds(30))
                .build();
    }
}
