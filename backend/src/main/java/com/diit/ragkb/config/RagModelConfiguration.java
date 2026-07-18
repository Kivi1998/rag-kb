package com.diit.ragkb.config;

import com.diit.ragkb.ragcore.embedding.EmbeddingClient;
import com.diit.ragkb.ragcore.embedding.OpenAiCompatibleEmbeddingClient;
import com.diit.ragkb.ragcore.generation.AnswerGenerator;
import com.diit.ragkb.ragcore.generation.ChatCompletionClient;
import com.diit.ragkb.ragcore.generation.OpenAiCompatibleAnswerGenerator;
import com.diit.ragkb.ragcore.generation.OpenAiCompatibleChatCompletionClient;
import com.diit.ragkb.ragcore.generation.PromptAssembler;
import com.diit.ragkb.ragcore.intent.LlmQueryIntentClassifier;
import com.diit.ragkb.ragcore.intent.QueryIntentClassifier;
import com.diit.ragkb.ragcore.nli.HttpNliClient;
import com.diit.ragkb.ragcore.nli.NliClient;
import com.diit.ragkb.ragcore.rerank.OpenAiCompatibleRerankerClient;
import com.diit.ragkb.ragcore.rerank.RerankerClient;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** 模型客户端装配；未配置端点时不创建 Bean，调用方必须走可识别的降级路径。 */
@Configuration
@EnableConfigurationProperties({RagModelProperties.class, RagNliProperties.class, RagIntentClassificationProperties.class})
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

    @Bean
    @ConditionalOnProperty(prefix = "rag.model.generation", name = "enabled", havingValue = "true")
    public AnswerGenerator answerGenerator(RagModelProperties properties, ObjectMapper objectMapper,
                                           PromptAssembler promptAssembler) {
        return new OpenAiCompatibleAnswerGenerator(properties.getGeneration(), objectMapper, promptAssembler);
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.nli", name = "enabled", havingValue = "true")
    public NliClient nliClient(RagNliProperties properties, ObjectMapper objectMapper) {
        return new HttpNliClient(properties, objectMapper);
    }

    /**
     * 独立于 {@code rag.memory} 子系统的 {@code chatCompletionClient} bean 装配——意图分类在概念上
     * 与会话记忆无关，不应该被迫要求先开启 {@code rag.memory.enabled}。复用同一个生成模型端点配置。
     */
    @Bean
    @ConditionalOnProperty(prefix = "rag.intent-classification", name = "enabled", havingValue = "true")
    public ChatCompletionClient intentClassificationChatCompletionClient(RagModelProperties properties,
                                                                         ObjectMapper objectMapper) {
        return new OpenAiCompatibleChatCompletionClient(properties.getGeneration(), objectMapper);
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.intent-classification", name = "enabled", havingValue = "true")
    public QueryIntentClassifier queryIntentClassifier(
            @Qualifier("intentClassificationChatCompletionClient") ChatCompletionClient client) {
        return new LlmQueryIntentClassifier(client);
    }
}
