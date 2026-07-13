package com.diit.ragkb.ragcore.ingestion;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.ApplicationContext;

import static org.junit.jupiter.api.Assertions.assertNotNull;

/** 防止 Worker 因配置条件注册顺序而被静默跳过。 */
@SpringBootTest(properties = {
        "spring.datasource.url=jdbc:h2:mem:worker-config;DB_CLOSE_DELAY=-1;MODE=PostgreSQL",
        "rag.ingestion.worker.enabled=true",
        "rag.ingestion.worker.poll-interval-ms=3600000",
        "rag.model.embedding.enabled=true",
        "rag.model.embedding.endpoint=http://127.0.0.1:9/v1/embeddings",
        "rag.model.embedding.model=test-embedding",
        "rag.elasticsearch.enabled=true",
        "rag.elasticsearch.endpoint=http://127.0.0.1:9",
        "rag.elasticsearch.vector-dimensions=8",
        "rag.elasticsearch.health-enabled=false"
})
class IngestionWorkerConfigurationTest {

    @Autowired
    private ApplicationContext context;

    @Test
    void workerBeanExistsWhenProductionSwitchIsEnabled() {
        assertNotNull(context.getBean(IngestionWorker.class));
        assertNotNull(context.getBean(DocumentIngestionPipeline.class));
    }
}
