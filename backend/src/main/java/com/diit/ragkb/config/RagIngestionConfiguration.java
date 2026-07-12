package com.diit.ragkb.config;

import com.diit.ragkb.ragcore.chunk.Chunker;
import com.diit.ragkb.ragcore.chunk.impl.TechnicalChunker;
import com.diit.ragkb.ragcore.embedding.EmbeddingClient;
import com.diit.ragkb.ragcore.index.ChunkIndex;
import com.diit.ragkb.ragcore.ingestion.DefaultDocumentIngestionPipeline;
import com.diit.ragkb.ragcore.ingestion.DocumentIngestionPipeline;
import com.diit.ragkb.ragcore.ingestion.IngestionJobLifecycleService;
import com.diit.ragkb.ragcore.parser.impl.DocumentParserFactory;
import com.diit.ragkb.ragcore.storage.ObjectStorage;
import com.diit.ragkb.ragcore.retrieval.HybridCandidateSource;
import com.diit.ragkb.ragcore.retrieval.HybridRetriever;
import com.diit.ragkb.ragcore.retrieval.Retriever;
import com.diit.ragkb.ragcore.rerank.RerankerClient;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** 自研 RAG 摄取管道装配，外部模型与 ES 未配置时不会误启动 Worker。 */
@Configuration
public class RagIngestionConfiguration {

    @Bean
    public DocumentParserFactory documentParserFactory() {
        return DocumentParserFactory.createDefault();
    }

    @Bean
    public Chunker technicalChunker() {
        return new TechnicalChunker();
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.ingestion.worker", name = "enabled", havingValue = "true")
    public DocumentIngestionPipeline documentIngestionPipeline(DocumentParserFactory parserFactory, Chunker chunker,
                                                               EmbeddingClient embeddingClient, ChunkIndex chunkIndex,
                                                               ObjectStorage objectStorage,
                                                               IngestionJobLifecycleService lifecycleService) {
        return new DefaultDocumentIngestionPipeline(parserFactory, chunker, embeddingClient, chunkIndex,
                objectStorage, lifecycleService);
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.retrieval", name = "enabled", havingValue = "true")
    public Retriever retriever(HybridCandidateSource candidateSource, EmbeddingClient embeddingClient,
                               ObjectProvider<RerankerClient> rerankerProvider) {
        return new HybridRetriever(candidateSource, embeddingClient, rerankerProvider);
    }
}
