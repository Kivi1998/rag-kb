package com.diit.ragkb.config;

import com.diit.ragkb.ragcore.conversation.ConversationMemoryOrchestrator;
import com.diit.ragkb.ragcore.generation.AnswerGenerator;
import com.diit.ragkb.ragcore.intent.QueryIntentClassifier;
import com.diit.ragkb.ragcore.quickdocument.QuickDocumentStore;
import com.diit.ragkb.ragcore.rerank.RerankerClient;
import com.diit.ragkb.ragcore.retrieval.Retriever;
import com.diit.ragkb.repository.IntentTrainingSampleRepository;
import com.diit.ragkb.repository.KnowledgeDocumentRepository;
import com.diit.ragkb.service.ChatSessionService;
import com.diit.ragkb.service.IntentTrainingSampleService;
import com.diit.ragkb.service.KnowledgeBaseService;
import com.diit.ragkb.service.QueryService;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.atomic.AtomicInteger;

/** 问答开关开启时，显式装配检索、生成和隔离的 SSE 执行器。 */
@Configuration
@EnableConfigurationProperties({RagQueryProperties.class, RagIntentTrainingDataProperties.class})
public class RagQueryConfiguration {

    @Bean
    @ConditionalOnProperty(prefix = "rag.query", name = "enabled", havingValue = "true")
    public QueryService queryService(Retriever retriever, AnswerGenerator answerGenerator,
                                     KnowledgeBaseService knowledgeBaseService,
                                     KnowledgeDocumentRepository documentRepository,
                                     ObjectProvider<ChatSessionService> chatSessionServiceProvider,
                                     ObjectProvider<ConversationMemoryOrchestrator> memoryOrchestratorProvider,
                                     ObjectProvider<RerankerClient> rerankerProvider,
                                     ObjectProvider<QueryIntentClassifier> intentClassifierProvider,
                                     ObjectProvider<QuickDocumentStore> quickDocumentStoreProvider) {
        return new QueryService(retriever, answerGenerator, knowledgeBaseService, documentRepository,
                chatSessionServiceProvider, memoryOrchestratorProvider, rerankerProvider, intentClassifierProvider,
                quickDocumentStoreProvider);
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.intent-training-data", name = "enabled", havingValue = "true")
    public IntentTrainingSampleService intentTrainingSampleService(IntentTrainingSampleRepository repository) {
        return new IntentTrainingSampleService(repository);
    }

    @Bean(destroyMethod = "shutdown", name = "ragQueryExecutor")
    @ConditionalOnProperty(prefix = "rag.query", name = "enabled", havingValue = "true")
    public ExecutorService ragQueryExecutor(RagQueryProperties properties) {
        if (properties.getWorkerThreads() <= 0 || properties.getStreamTimeoutMs() <= 0) {
            throw new IllegalArgumentException("rag.query.worker-threads 与 stream-timeout-ms 必须大于 0");
        }
        AtomicInteger sequence = new AtomicInteger();
        ThreadFactory threadFactory = runnable -> {
            Thread thread = new Thread(runnable, "rag-query-" + sequence.incrementAndGet());
            thread.setDaemon(true);
            return thread;
        };
        return Executors.newFixedThreadPool(properties.getWorkerThreads(), threadFactory);
    }
}
