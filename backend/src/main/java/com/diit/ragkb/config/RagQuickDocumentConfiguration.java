package com.diit.ragkb.config;

import com.diit.ragkb.ragcore.parser.impl.DocumentParserFactory;
import com.diit.ragkb.ragcore.quickdocument.QuickDocumentService;
import com.diit.ragkb.ragcore.quickdocument.QuickDocumentStore;
import com.diit.ragkb.ragcore.quickdocument.RedisQuickDocumentStore;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.autoconfigure.data.redis.RedisProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * 会话内临时文档子系统装配；独立于 {@code rag.memory}，用独立 Redis 逻辑 DB（默认 2）。
 * {@code rag.quick-document.enabled=false} 时不创建任何 Bean，问答退化为不支持临时文档
 * （{@code ObjectProvider} 取不到 {@link QuickDocumentStore}）。
 */
@Configuration
@EnableConfigurationProperties(RagQuickDocumentProperties.class)
public class RagQuickDocumentConfiguration {

    @Bean(name = "quickDocumentRedisConnectionFactory")
    @ConditionalOnProperty(prefix = "rag.quick-document", name = "enabled", havingValue = "true")
    public RedisConnectionFactory quickDocumentRedisConnectionFactory(RedisProperties redisProperties,
                                                                      RagQuickDocumentProperties properties) {
        RedisStandaloneConfiguration config = new RedisStandaloneConfiguration(redisProperties.getHost(),
                redisProperties.getPort());
        config.setDatabase(properties.getRedisDatabase());
        if (redisProperties.getPassword() != null && !redisProperties.getPassword().isBlank()) {
            config.setPassword(redisProperties.getPassword());
        }
        return new LettuceConnectionFactory(config);
    }

    @Bean(name = "quickDocumentRedisTemplate", destroyMethod = "")
    @ConditionalOnProperty(prefix = "rag.quick-document", name = "enabled", havingValue = "true")
    public StringRedisTemplate quickDocumentRedisTemplate(
            @Qualifier("quickDocumentRedisConnectionFactory") RedisConnectionFactory connectionFactory) {
        StringRedisTemplate template = new StringRedisTemplate();
        template.setConnectionFactory(connectionFactory);
        template.afterPropertiesSet();
        return template;
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.quick-document", name = "enabled", havingValue = "true")
    public QuickDocumentStore quickDocumentStore(
            @Qualifier("quickDocumentRedisTemplate") StringRedisTemplate redisTemplate,
            RagQuickDocumentProperties properties, ObjectMapper objectMapper) {
        return new RedisQuickDocumentStore(redisTemplate, properties, objectMapper);
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.quick-document", name = "enabled", havingValue = "true")
    public QuickDocumentService quickDocumentService(DocumentParserFactory parserFactory,
                                                      QuickDocumentStore store, RagQuickDocumentProperties properties) {
        return new QuickDocumentService(parserFactory, store, properties);
    }
}
