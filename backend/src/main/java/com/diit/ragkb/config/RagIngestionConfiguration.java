package com.diit.ragkb.config;

import com.diit.ragkb.ragcore.chunk.Chunker;
import com.diit.ragkb.ragcore.chunk.impl.TechnicalChunker;
import com.diit.ragkb.ragcore.embedding.EmbeddingClient;
import com.diit.ragkb.ragcore.index.LexicalChunkIndex;
import com.diit.ragkb.ragcore.index.VectorChunkIndex;
import com.diit.ragkb.ragcore.ingestion.ChunkProjectionOrchestrator;
import com.diit.ragkb.ragcore.ingestion.DefaultDocumentIngestionPipeline;
import com.diit.ragkb.ragcore.ingestion.DocumentIngestionPipeline;
import com.diit.ragkb.ragcore.ingestion.IngestionJobLifecycleService;
import com.diit.ragkb.ragcore.ingestion.IngestionMetrics;
import com.diit.ragkb.ragcore.ingestion.ParsedArtifactStore;
import com.diit.ragkb.ragcore.parser.impl.DocumentParserFactory;
import com.diit.ragkb.ragcore.parser.MultimodalDocumentParser;
import com.diit.ragkb.ragcore.parser.impl.HttpMultimodalDocumentParser;
import com.diit.ragkb.ragcore.storage.ObjectStorage;
import com.diit.ragkb.ragcore.retrieval.ChunkHydrator;
import com.diit.ragkb.ragcore.retrieval.HybridRetriever;
import com.diit.ragkb.ragcore.retrieval.LexicalCandidateSource;
import com.diit.ragkb.ragcore.retrieval.Retriever;
import com.diit.ragkb.ragcore.retrieval.VectorCandidateSource;
import com.diit.ragkb.ragcore.retrieval.VectorRetrievalMetrics;
import com.diit.ragkb.ragcore.rerank.RerankerClient;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.beans.factory.annotation.Value;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;

/** 自研 RAG 摄取管道装配，外部模型与 ES 未配置时不会误启动 Worker。 */
@Configuration
public class RagIngestionConfiguration {

    @Bean
    public DocumentParserFactory documentParserFactory(ObjectProvider<MultimodalDocumentParser> multimodalParserProvider) {
        return DocumentParserFactory.createDefault(multimodalParserProvider.getIfAvailable());
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.parser.multimodal", name = "enabled", havingValue = "true")
    public MultimodalDocumentParser multimodalDocumentParser(
            com.fasterxml.jackson.databind.ObjectMapper objectMapper,
            @Value("${rag.parser.multimodal.endpoint:}") String endpoint,
            @Value("${rag.parser.multimodal.api-key:}") String apiKey,
            @Value("${rag.parser.multimodal.timeout-ms:600000}") long timeoutMs) {
        return new HttpMultimodalDocumentParser(objectMapper, endpoint, apiKey, timeoutMs);
    }

    @Bean
    public Chunker technicalChunker() {
        return new TechnicalChunker();
    }

    /**
     * 摄取任务独立线程池。队列容量设为 0，背压由 Worker 的 in-flight 上限承担，
     * 防止大量 PDF/OCR 任务堆积在单个 JVM 内存中。
     */
    @Bean(name = "ingestionTaskExecutor")
    @ConditionalOnProperty(prefix = "rag.ingestion.worker", name = "enabled", havingValue = "true")
    public ThreadPoolTaskExecutor ingestionTaskExecutor(
            @Value("${rag.ingestion.worker.concurrency:4}") int concurrency) {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(concurrency);
        executor.setMaxPoolSize(concurrency);
        executor.setQueueCapacity(0);
        executor.setThreadNamePrefix("rag-ingestion-");
        executor.setWaitForTasksToCompleteOnShutdown(true);
        executor.setAwaitTerminationSeconds(60);
        executor.initialize();
        return executor;
    }

    /** 长耗时 OCR/ASR 使用独立线程续租，避免业务线程阻塞时任务被重复领取。 */
    @Bean(name = "ingestionHeartbeatExecutor", destroyMethod = "shutdown")
    @ConditionalOnProperty(prefix = "rag.ingestion.worker", name = "enabled", havingValue = "true")
    public ScheduledExecutorService ingestionHeartbeatExecutor(
            @Value("${rag.ingestion.worker.concurrency:4}") int concurrency) {
        return Executors.newScheduledThreadPool(Math.min(Math.max(1, concurrency), 4), runnable -> {
            Thread thread = new Thread(runnable, "rag-ingestion-heartbeat");
            thread.setDaemon(true);
            return thread;
        });
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.ingestion.worker", name = "enabled", havingValue = "true")
    public ChunkProjectionOrchestrator chunkProjectionOrchestrator(LexicalChunkIndex lexicalChunkIndex,
                                                                    ObjectProvider<VectorChunkIndex> vectorProvider) {
        return new ChunkProjectionOrchestrator(lexicalChunkIndex, vectorProvider.getIfAvailable());
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.ingestion.worker", name = "enabled", havingValue = "true")
    public DocumentIngestionPipeline documentIngestionPipeline(DocumentParserFactory parserFactory, Chunker chunker,
                                                               EmbeddingClient embeddingClient,
                                                               ChunkProjectionOrchestrator projectionOrchestrator,
                                                               ObjectStorage objectStorage,
                                                               IngestionJobLifecycleService lifecycleService,
                                                               ParsedArtifactStore artifactStore,
                                                               IngestionMetrics metrics) {
        return new DefaultDocumentIngestionPipeline(parserFactory, chunker, embeddingClient, projectionOrchestrator,
                objectStorage, lifecycleService, artifactStore, metrics);
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.retrieval", name = "enabled", havingValue = "true")
    public Retriever retriever(LexicalCandidateSource lexicalCandidateSource,
                               VectorCandidateSource vectorCandidateSource,
                               ChunkHydrator chunkHydrator,
                               EmbeddingClient embeddingClient,
                               VectorRetrievalMetrics vectorMetrics,
                               ObjectProvider<RerankerClient> rerankerProvider) {
        return new HybridRetriever(lexicalCandidateSource, vectorCandidateSource, chunkHydrator,
                embeddingClient, rerankerProvider, vectorMetrics);
    }
}
