package com.diit.ragkb.config;

import com.diit.ragkb.ragcore.index.ElasticsearchVisibilityBackfill;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.elasticsearch.client.RestClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** 一次性存量可见性回填命令；普通服务启动默认不创建。 */
@Slf4j
@Configuration(proxyBeanMethods = false)
public class RagElasticsearchBackfillConfiguration {

    @Bean
    @ConditionalOnProperty(prefix = "rag.elasticsearch.visibility-backfill", name = "enabled", havingValue = "true")
    ApplicationRunner visibilityBackfillRunner(RestClient ragRestClient, RagElasticsearchProperties properties,
                                               ObjectMapper objectMapper,
                                               @Value("${rag.elasticsearch.visibility-backfill.dry-run:true}") boolean dryRun,
                                               @Value("${rag.elasticsearch.visibility-backfill.batch-size:500}") int batchSize,
                                               @Value("${rag.elasticsearch.visibility-backfill.max-attempts:3}") int maxAttempts) {
        return args -> {
            var result = new ElasticsearchVisibilityBackfill(ragRestClient, properties, objectMapper)
                    .run(dryRun, batchSize, maxAttempts);
            log.info("ES retrieval_ready 回填完成: dryRun={}, missingBefore={}, updated={}, missingAfter={}",
                    result.dryRun(), result.missingBefore(), result.updated(), result.missingAfter());
            if (!result.dryRun() && result.missingAfter() != 0) {
                throw new IllegalStateException("ES retrieval_ready 回填后仍有 " + result.missingAfter() + " 条缺失");
            }
        };
    }
}
