package com.diit.ragkb.config;

import com.diit.ragkb.ragcore.index.MilvusCollectionManager;
import com.diit.ragkb.ragcore.index.MilvusVectorIndex;
import com.diit.ragkb.ragcore.index.VectorChunkIndex;
import com.diit.ragkb.ragcore.retrieval.MilvusVectorCandidateSource;
import io.milvus.v2.client.ConnectConfig;
import io.milvus.v2.client.MilvusClientV2;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Milvus 客户端与向量投影装配；Collection 不兼容时启动即失败。 */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = "rag.milvus", name = "enabled", havingValue = "true")
public class RagMilvusConfiguration {

    @Bean
    @ConditionalOnMissingBean
    MilvusClientFactory milvusClientFactory() {
        return MilvusClientV2::new;
    }

    @Bean(destroyMethod = "close")
    MilvusClientV2 ragMilvusClient(RagMilvusProperties properties, MilvusClientFactory factory) {
        return factory.create(connectConfig(properties));
    }

    ConnectConfig connectConfig(RagMilvusProperties properties) {
        var builder = ConnectConfig.builder()
                .uri(properties.getUri())
                .dbName(properties.getDatabaseName())
                .connectTimeoutMs(properties.getConnectTimeoutMs())
                .rpcDeadlineMs(properties.getRpcTimeoutMs())
                .secure(properties.isTlsEnabled())
                .enablePrecheck(true);
        if (properties.isAuthEnabled()) {
            if (properties.getToken() != null && !properties.getToken().isBlank()) {
                builder.token(properties.getToken());
            } else {
                builder.username(properties.getUsername()).password(properties.getPassword());
            }
        }
        return builder.build();
    }

    @Bean
    MilvusCollectionManager milvusCollectionManager(MilvusClientV2 ragMilvusClient,
                                                     RagMilvusProperties properties) {
        return new MilvusCollectionManager(ragMilvusClient, properties);
    }

    @Bean
    ApplicationRunner milvusCollectionInitializer(MilvusCollectionManager manager) {
        return args -> manager.ensureReady();
    }

    @Bean
    VectorChunkIndex milvusVectorIndex(MilvusClientV2 ragMilvusClient, RagMilvusProperties properties) {
        return new MilvusVectorIndex(ragMilvusClient, properties);
    }

    @Bean
    MilvusVectorCandidateSource milvusVectorCandidateSource(MilvusClientV2 ragMilvusClient,
                                                            RagMilvusProperties properties) {
        return new MilvusVectorCandidateSource(ragMilvusClient, properties);
    }
}
