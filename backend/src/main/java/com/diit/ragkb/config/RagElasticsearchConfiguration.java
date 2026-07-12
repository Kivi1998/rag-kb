package com.diit.ragkb.config;

import com.diit.ragkb.ragcore.index.ChunkIndex;
import com.diit.ragkb.ragcore.index.ElasticsearchChunkIndex;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.http.Header;
import org.apache.http.message.BasicHeader;
import org.elasticsearch.client.RestClient;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Elasticsearch 原生 Java Client 装配；未显式启用时不会尝试连接外部集群。 */
@Configuration
@EnableConfigurationProperties(RagElasticsearchProperties.class)
public class RagElasticsearchConfiguration {

    @Bean(destroyMethod = "close")
    @ConditionalOnProperty(prefix = "rag.elasticsearch", name = "enabled", havingValue = "true")
    public RestClient ragRestClient(RagElasticsearchProperties properties) {
        validate(properties);
        var builder = RestClient.builder(org.apache.http.HttpHost.create(properties.getEndpoint()))
                .setRequestConfigCallback(config -> config
                        .setConnectTimeout(properties.getConnectTimeoutMs())
                        .setSocketTimeout(properties.getSocketTimeoutMs()));
        if (properties.getApiKey() != null && !properties.getApiKey().isBlank()) {
            Header authorization = new BasicHeader("Authorization", "ApiKey " + properties.getApiKey());
            builder.setDefaultHeaders(new Header[]{authorization});
        }
        return builder.build();
    }

    @Bean
    @ConditionalOnProperty(prefix = "rag.elasticsearch", name = "enabled", havingValue = "true")
    public ChunkIndex chunkIndex(RestClient ragRestClient, RagElasticsearchProperties properties,
                                 ObjectMapper objectMapper) {
        return new ElasticsearchChunkIndex(ragRestClient, properties, objectMapper);
    }

    private void validate(RagElasticsearchProperties properties) {
        if (properties.getEndpoint() == null || properties.getEndpoint().isBlank()
                || properties.getIndexName() == null || properties.getIndexName().isBlank()
                || properties.getVectorDimensions() <= 0
                || properties.getConnectTimeoutMs() <= 0 || properties.getSocketTimeoutMs() <= 0) {
            throw new IllegalStateException("启用 Elasticsearch 前必须配置 endpoint/index-name/vector-dimensions 与正数超时");
        }
    }
}
