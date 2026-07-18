package com.diit.ragkb.config;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;

class RagVectorPropertiesConfigurationTest {

    private final ApplicationContextRunner runner = new ApplicationContextRunner()
            .withUserConfiguration(RagVectorPropertiesConfiguration.class);

    @Test
    void defaultsKeepExistingElasticsearchPathDisabledFromMilvus() {
        runner.run(context -> {
            assertFalse(context.getBean(RagMilvusProperties.class).isEnabled());
            assertEquals(VectorProvider.ELASTICSEARCH,
                    context.getBean(VectorProviderProperties.class).getProvider());
            assertFalse(context.getStartupFailure() != null);
        });
    }

    @Test
    void bindsValidMilvusProperties() {
        runner.withPropertyValues(
                "rag.vector.provider=milvus",
                "rag.milvus.enabled=true",
                "rag.milvus.uri=http://localhost:19530",
                "rag.milvus.vector-dimensions=1024",
                "rag.milvus.search-ef=96")
                .run(context -> {
                    assertEquals(null, context.getStartupFailure());
                    assertEquals(96, context.getBean(RagMilvusProperties.class).getSearchEf());
                    assertEquals(VectorProvider.MILVUS,
                            context.getBean(VectorProviderProperties.class).getProvider());
                });
    }

    @Test
    void rejectsMilvusProviderWhenMilvusIsDisabled() {
        runner.withPropertyValues("rag.vector.provider=milvus")
                .run(context -> assertEquals(IllegalStateException.class,
                        rootCause(context.getStartupFailure()).getClass()));
    }

    @Test
    void rejectsInvalidDimensions() {
        runner.withPropertyValues(
                "rag.milvus.enabled=true",
                "rag.milvus.uri=http://localhost:19530",
                "rag.milvus.vector-dimensions=0")
                .run(context -> assertEquals(IllegalStateException.class,
                        rootCause(context.getStartupFailure()).getClass()));
    }

    @Test
    void rejectsMissingCredentialsWhenAuthenticationIsEnabled() {
        runner.withPropertyValues(
                "rag.milvus.enabled=true",
                "rag.milvus.uri=http://localhost:19530",
                "rag.milvus.auth-enabled=true")
                .run(context -> assertEquals(IllegalStateException.class,
                        rootCause(context.getStartupFailure()).getClass()));
    }

    @Test
    void rejectsUnknownProviderDuringBinding() {
        runner.withPropertyValues("rag.vector.provider=unknown")
                .run(context -> org.junit.jupiter.api.Assertions.assertNotNull(context.getStartupFailure()));
    }

    private Throwable rootCause(Throwable failure) {
        Throwable current = failure;
        while (current != null && current.getCause() != null) current = current.getCause();
        return current;
    }
}
