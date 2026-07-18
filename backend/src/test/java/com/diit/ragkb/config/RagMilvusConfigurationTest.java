package com.diit.ragkb.config;

import io.milvus.v2.client.MilvusClientV2;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class RagMilvusConfigurationTest {

    @Test
    void buildsTlsTokenAndTimeoutConfigurationWithoutOpeningConnection() {
        RagMilvusProperties properties = properties();
        properties.setAuthEnabled(true);
        properties.setToken("secret-token");
        properties.setTlsEnabled(true);
        properties.setConnectTimeoutMs(1_234);
        properties.setRpcTimeoutMs(5_678);

        var config = new RagMilvusConfiguration().connectConfig(properties);

        assertEquals("http://localhost:19530", config.getUri());
        assertEquals("secret-token", config.getToken());
        assertEquals(1_234, config.getConnectTimeoutMs());
        assertEquals(5_678, config.getRpcDeadlineMs());
        assertTrue(config.isSecure());
    }

    @Test
    void closesSdkClientWhenSpringContextStops() {
        MilvusClientV2 client = mock(MilvusClientV2.class);
        when(client.hasCollection(any())).thenReturn(false);
        AtomicReference<MilvusClientV2> created = new AtomicReference<>();
        ApplicationContextRunner runner = new ApplicationContextRunner()
                .withUserConfiguration(RagVectorPropertiesConfiguration.class, RagMilvusConfiguration.class)
                .withBean(MilvusClientFactory.class, () -> connectConfig -> {
                    created.set(client);
                    return client;
                })
                .withPropertyValues(
                        "rag.milvus.enabled=true",
                        "rag.milvus.uri=http://localhost:19530",
                        "rag.milvus.vector-dimensions=2");

        runner.run(context -> assertEquals(client, created.get()));

        verify(client).close();
    }

    private RagMilvusProperties properties() {
        RagMilvusProperties properties = new RagMilvusProperties();
        properties.setEnabled(true);
        properties.setUri("http://localhost:19530");
        properties.setVectorDimensions(2);
        return properties;
    }
}
