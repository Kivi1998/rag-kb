package com.diit.ragkb.config;

import com.diit.ragkb.ragcore.embedding.EmbeddingClient;
import com.diit.ragkb.ragcore.embedding.OpenAiCompatibleEmbeddingClient;
import com.diit.ragkb.ragcore.rerank.OpenAiCompatibleRerankerClient;
import com.diit.ragkb.ragcore.rerank.RerankerClient;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** 模型客户端装配；未配置端点时不创建 Bean，调用方必须走可识别的降级路径。 */
@Configuration
@EnableConfigurationProperties(RagModelProperties.class)
public class RagModelConfiguration {

    @Bean
    @ConditionalOnProperty(prefix = "rag.model.embedding", name = "enabled", havingValue = "true")
    public EmbeddingClient embeddingClient(RagModelProperties properties, ObjectMapper objectMapper) {
        return new OpenAiCompatibleEmbeddingClient(properties.getEmbedding(), objectMapper);
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.model.rerank", name = "enabled", havingValue = "true")
    public RerankerClient rerankerClient(RagModelProperties properties, ObjectMapper objectMapper) {
        return new OpenAiCompatibleRerankerClient(properties.getRerank(), objectMapper);
    }
}
