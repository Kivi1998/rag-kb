package com.diit.ragkb.config;

import com.diit.ragkb.ragcore.conversation.ConversationMemoryOrchestrator;
import com.diit.ragkb.ragcore.conversation.ConversationStore;
import com.diit.ragkb.ragcore.conversation.ConversationSummarizer;
import com.diit.ragkb.ragcore.conversation.CoreferenceResolver;
import com.diit.ragkb.ragcore.conversation.MemoryExtractor;
import com.diit.ragkb.ragcore.conversation.MemoryIndex;
import com.diit.ragkb.ragcore.conversation.MemoryItemRepository;
import com.diit.ragkb.ragcore.conversation.ChatMessageRepository;
import com.diit.ragkb.ragcore.conversation.MemoryItemStore;
import com.diit.ragkb.ragcore.conversation.SlidingWindowAssembler;
import com.diit.ragkb.ragcore.conversation.UserProfileInjector;
import com.diit.ragkb.ragcore.conversation.impl.DeepSeekConversationSummarizer;
import com.diit.ragkb.ragcore.conversation.impl.DeepSeekCoreferenceResolver;
import com.diit.ragkb.ragcore.conversation.impl.DeepSeekMemoryExtractor;
import com.diit.ragkb.ragcore.conversation.impl.ElasticsearchMemoryIndex;
import com.diit.ragkb.ragcore.conversation.impl.MemoryCleanupTask;
import com.diit.ragkb.ragcore.conversation.impl.MemoryItemStoreImpl;
import com.diit.ragkb.ragcore.conversation.impl.RedisMongoConversationStore;
import com.diit.ragkb.ragcore.embedding.EmbeddingClient;
import com.diit.ragkb.ragcore.generation.ChatCompletionClient;
import com.diit.ragkb.ragcore.generation.OpenAiCompatibleChatCompletionClient;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.elasticsearch.client.RestClient;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.autoconfigure.data.redis.RedisProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.mongodb.core.MongoTemplate;
import org.springframework.data.mongodb.core.SimpleMongoClientDatabaseFactory;
import org.springframework.data.mongodb.repository.config.EnableMongoRepositories;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * 多轮对话与记忆管理子系统装配；{@code rag.memory.enabled=false} 时不创建任何 Bean，
 * 问答退化为无记忆单轮（{@code sessionId} 仍必填，但不做滑动窗口/画像注入）。
 *
 * <p>Redis 用独立的逻辑 DB（见 {@link RagMemoryProperties#getRedisDatabase()}），
 * 与 JWT 黑名单（DB 0）物理隔离；MongoDB 只服务本子系统，不涉及其他业务表。</p>
 */
@Configuration
@ConditionalOnProperty(prefix = "rag.memory", name = "enabled", havingValue = "true")
@EnableConfigurationProperties(RagMemoryProperties.class)
@EnableMongoRepositories(basePackageClasses = {ChatMessageRepository.class, MemoryItemRepository.class})
public class RagMemoryConfiguration {

    @Bean(name = "memoryRedisConnectionFactory")
    @ConditionalOnProperty(prefix = "rag.memory", name = "enabled", havingValue = "true")
    public RedisConnectionFactory memoryRedisConnectionFactory(RedisProperties redisProperties,
                                                               RagMemoryProperties memoryProperties) {
        RedisStandaloneConfiguration config = new RedisStandaloneConfiguration(redisProperties.getHost(),
                redisProperties.getPort());
        config.setDatabase(memoryProperties.getRedisDatabase());
        if (redisProperties.getPassword() != null && !redisProperties.getPassword().isBlank()) {
            config.setPassword(redisProperties.getPassword());
        }
        return new LettuceConnectionFactory(config);
    }

    @Bean(name = "memoryRedisTemplate", destroyMethod = "")
    @ConditionalOnProperty(prefix = "rag.memory", name = "enabled", havingValue = "true")
    public StringRedisTemplate memoryRedisTemplate(
            @Qualifier("memoryRedisConnectionFactory") RedisConnectionFactory connectionFactory) {
        StringRedisTemplate template = new StringRedisTemplate();
        template.setConnectionFactory(connectionFactory);
        template.afterPropertiesSet();
        return template;
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.memory", name = "enabled", havingValue = "true")
    public MongoTemplate mongoTemplate(RagMemoryProperties properties) {
        if (properties.getMongoUri() == null || properties.getMongoUri().isBlank()) {
            throw new IllegalStateException("启用会话记忆前必须配置 rag.memory.mongo-uri");
        }
        // 单参数构造函数直接从连接串解析出数据库名，不需要单独维护 MongoClient Bean。
        return new MongoTemplate(new SimpleMongoClientDatabaseFactory(properties.getMongoUri()));
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.memory", name = "enabled", havingValue = "true")
    public MemoryIndex memoryIndex(RestClient ragRestClient, RagElasticsearchProperties esProperties,
                                   RagMemoryProperties memoryProperties, ObjectMapper objectMapper) {
        return new ElasticsearchMemoryIndex(ragRestClient, esProperties, memoryProperties, objectMapper);
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.memory", name = "enabled", havingValue = "true")
    public ConversationStore conversationStore(
            @Qualifier("memoryRedisTemplate") StringRedisTemplate memoryRedisTemplate,
            ChatMessageRepository chatMessageRepository, ObjectMapper objectMapper) {
        return new RedisMongoConversationStore(memoryRedisTemplate, chatMessageRepository, objectMapper);
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.memory", name = "enabled", havingValue = "true")
    public MemoryItemStore memoryItemStore(MemoryIndex memoryIndex, MemoryItemRepository memoryItemRepository,
                                           RagMemoryProperties properties) {
        return new MemoryItemStoreImpl(memoryIndex, memoryItemRepository, properties);
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.memory", name = "enabled", havingValue = "true")
    public ChatCompletionClient chatCompletionClient(RagModelProperties modelProperties, ObjectMapper objectMapper) {
        return new OpenAiCompatibleChatCompletionClient(modelProperties.getGeneration(), objectMapper);
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.memory", name = "enabled", havingValue = "true")
    public CoreferenceResolver coreferenceResolver(ChatCompletionClient chatCompletionClient) {
        return new DeepSeekCoreferenceResolver(chatCompletionClient);
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.memory", name = "enabled", havingValue = "true")
    public ConversationSummarizer conversationSummarizer(ChatCompletionClient chatCompletionClient) {
        return new DeepSeekConversationSummarizer(chatCompletionClient);
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.memory", name = "enabled", havingValue = "true")
    public SlidingWindowAssembler slidingWindowAssembler(ConversationSummarizer summarizer) {
        return new SlidingWindowAssembler(summarizer);
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.memory", name = "enabled", havingValue = "true")
    public MemoryExtractor memoryExtractor(ChatCompletionClient chatCompletionClient, EmbeddingClient embeddingClient,
                                           MemoryItemStore memoryItemStore, ObjectMapper objectMapper) {
        return new DeepSeekMemoryExtractor(chatCompletionClient, embeddingClient, memoryItemStore, objectMapper);
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.memory", name = "enabled", havingValue = "true")
    public UserProfileInjector userProfileInjector(MemoryItemStore memoryItemStore, RagMemoryProperties properties) {
        return new UserProfileInjector(memoryItemStore, properties.getProfileTopK());
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.memory", name = "enabled", havingValue = "true")
    public MemoryCleanupTask memoryCleanupTask(MemoryItemStore memoryItemStore, RagMemoryProperties properties) {
        return new MemoryCleanupTask(memoryItemStore, properties);
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.memory", name = "enabled", havingValue = "true")
    public ConversationMemoryOrchestrator conversationMemoryOrchestrator(ConversationStore conversationStore,
            SlidingWindowAssembler slidingWindowAssembler, CoreferenceResolver coreferenceResolver,
            EmbeddingClient embeddingClient, UserProfileInjector userProfileInjector,
            MemoryExtractor memoryExtractor, RagMemoryProperties properties) {
        return new ConversationMemoryOrchestrator(conversationStore, slidingWindowAssembler, coreferenceResolver,
                embeddingClient, userProfileInjector, memoryExtractor, properties.getTokenBudget());
    }
}
