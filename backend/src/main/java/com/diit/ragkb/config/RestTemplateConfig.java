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

    /** 通用 RAGFlow REST 客户端(30s 读超时) */
    @Bean
    public RestTemplate ragFlowRestTemplate(RagFlowProperties properties) {
        return new RestTemplateBuilder()
                .defaultHeader("Authorization", "Bearer " + properties.getApiKey())
                .setConnectTimeout(Duration.ofSeconds(10))
                .setReadTimeout(Duration.ofSeconds(30))
                .build();
    }

    /** 流式 SSE 客户端(5 分钟读超时,用于长文本问答) */
    @Bean
    public RestTemplate ragFlowStreamingRestTemplate(RagFlowProperties properties) {
        return new RestTemplateBuilder()
                .defaultHeader("Authorization", "Bearer " + properties.getApiKey())
                .setConnectTimeout(Duration.ofSeconds(10))
                .setReadTimeout(Duration.ofMinutes(5))
                .build();
    }
}
