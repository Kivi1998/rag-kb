package com.diit.ragkb.config;

import com.diit.ragkb.ragcore.retrieval.MilvusVectorCandidateSource;
import com.diit.ragkb.ragcore.retrieval.ProviderVectorCandidateSource;
import com.diit.ragkb.ragcore.retrieval.VectorCandidateSource;
import com.diit.ragkb.ragcore.retrieval.VectorRetrievalMetrics;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** 三种向量读取模式的服务端装配。 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = "rag.elasticsearch", name = "enabled", havingValue = "true")
public class RagVectorProviderConfiguration {

    @Bean
    VectorRetrievalMetrics vectorRetrievalMetrics(MeterRegistry meterRegistry) {
        return new VectorRetrievalMetrics(meterRegistry);
    }

    @Bean(name = "vectorShadowExecutor", destroyMethod = "shutdown")
    ExecutorService vectorShadowExecutor() {
        return Executors.newFixedThreadPool(2, runnable -> {
            Thread thread = new Thread(runnable, "rag-vector-shadow");
            thread.setDaemon(true);
            return thread;
        });
    }

    @Bean
    @Primary
    VectorCandidateSource vectorCandidateSource(
            @Qualifier("elasticsearchVectorCandidateSource") VectorCandidateSource elasticsearch,
            ObjectProvider<MilvusVectorCandidateSource> milvusProvider,
            VectorProviderProperties properties,
            VectorRetrievalMetrics metrics,
            @Qualifier("vectorShadowExecutor") ExecutorService shadowExecutor) {
        return new ProviderVectorCandidateSource(elasticsearch, milvusProvider.getIfAvailable(), properties,
                metrics, shadowExecutor);
    }
}
