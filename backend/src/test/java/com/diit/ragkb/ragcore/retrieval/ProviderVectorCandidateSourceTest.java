package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.config.VectorProvider;
import com.diit.ragkb.config.VectorProviderProperties;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ProviderVectorCandidateSourceTest {

    @Test
    void elasticsearchModeUsesOnlyElasticsearch() {
        VectorCandidateSource elasticsearch = mock(VectorCandidateSource.class);
        VectorCandidateSource milvus = mock(VectorCandidateSource.class);
        VectorSearchRequest request = request();
        List<VectorHit> expected = List.of(new VectorHit("es", 1, 0.8));
        when(elasticsearch.search(request)).thenReturn(expected);

        List<VectorHit> actual = source(VectorProvider.ELASTICSEARCH, elasticsearch, milvus, true).search(request);

        assertEquals(expected, actual);
        verify(milvus, never()).search(request);
    }

    @Test
    void milvusModeFallsBackToElasticsearchWithSameTenantRequest() {
        VectorCandidateSource elasticsearch = mock(VectorCandidateSource.class);
        VectorCandidateSource milvus = mock(VectorCandidateSource.class);
        VectorSearchRequest request = request();
        when(milvus.search(request)).thenThrow(new RuntimeException("down"));
        when(elasticsearch.search(request)).thenReturn(List.of(new VectorHit("es", 1, 0.7)));

        List<VectorHit> actual = source(VectorProvider.MILVUS, elasticsearch, milvus, true).search(request);

        assertEquals("es", actual.get(0).chunkId());
        verify(milvus).search(request);
        verify(elasticsearch).search(request);
    }

    @Test
    void bothVectorSourcesFailAndQueryDegradesToEmptyVectorLeg() {
        VectorCandidateSource elasticsearch = mock(VectorCandidateSource.class);
        VectorCandidateSource milvus = mock(VectorCandidateSource.class);
        VectorSearchRequest request = request();
        when(milvus.search(request)).thenThrow(new RuntimeException("milvus down"));
        when(elasticsearch.search(request)).thenThrow(new RuntimeException("es down"));

        assertTrue(source(VectorProvider.MILVUS, elasticsearch, milvus, true).search(request).isEmpty());
    }

    @Test
    void disablingFallbackSurfacesMilvusFailure() {
        VectorCandidateSource elasticsearch = mock(VectorCandidateSource.class);
        VectorCandidateSource milvus = mock(VectorCandidateSource.class);
        VectorSearchRequest request = request();
        when(milvus.search(request)).thenThrow(new RuntimeException("down"));

        assertThrows(RuntimeException.class,
                () -> source(VectorProvider.MILVUS, elasticsearch, milvus, false).search(request));

        verify(elasticsearch, never()).search(request);
    }

    @Test
    void shadowModeReturnsEsResultAndDoesNotReplaceItWithMilvus() {
        VectorCandidateSource elasticsearch = mock(VectorCandidateSource.class);
        VectorCandidateSource milvus = mock(VectorCandidateSource.class);
        VectorSearchRequest request = request();
        when(elasticsearch.search(request)).thenReturn(List.of(new VectorHit("es", 1, 0.7)));
        when(milvus.search(request)).thenReturn(List.of(new VectorHit("milvus", 1, 0.9)));

        List<VectorHit> actual = source(VectorProvider.SHADOW, elasticsearch, milvus, true).search(request);

        assertEquals(List.of(new VectorHit("es", 1, 0.7)), actual);
        verify(milvus).search(request);
    }

    @Test
    void shadowTimeoutDoesNotDelayOrReplaceOnlineEsResult() throws Exception {
        VectorCandidateSource elasticsearch = mock(VectorCandidateSource.class);
        VectorCandidateSource milvus = mock(VectorCandidateSource.class);
        VectorSearchRequest request = request();
        when(elasticsearch.search(request)).thenReturn(List.of(new VectorHit("es", 1, 0.7)));
        when(milvus.search(request)).thenAnswer(invocation -> {
            TimeUnit.MILLISECONDS.sleep(200);
            return List.of(new VectorHit("milvus", 1, 0.9));
        });
        VectorProviderProperties properties = new VectorProviderProperties();
        properties.setProvider(VectorProvider.SHADOW);
        properties.setShadowSampleRate(1.0);
        properties.setShadowTimeoutMs(20);
        SimpleMeterRegistry registry = new SimpleMeterRegistry();
        var executor = Executors.newSingleThreadExecutor();
        var source = new ProviderVectorCandidateSource(elasticsearch, milvus, properties,
                new VectorRetrievalMetrics(registry), executor);

        long started = System.nanoTime();
        List<VectorHit> actual = source.search(request);
        long elapsedMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started);
        TimeUnit.MILLISECONDS.sleep(80);
        executor.shutdownNow();

        assertEquals(List.of(new VectorHit("es", 1, 0.7)), actual);
        assertTrue(elapsedMs < 100);
        assertEquals(1, registry.find("rag.vector.fallback")
                .tag("path", "shadow_timeout_or_failure").counter().count());
    }

    private ProviderVectorCandidateSource source(VectorProvider provider, VectorCandidateSource elasticsearch,
                                                  VectorCandidateSource milvus, boolean fallback) {
        VectorProviderProperties properties = new VectorProviderProperties();
        properties.setProvider(provider);
        properties.setFallbackToElasticsearch(fallback);
        properties.setShadowSampleRate(1.0);
        return new ProviderVectorCandidateSource(elasticsearch, milvus, properties,
                new VectorRetrievalMetrics(new SimpleMeterRegistry()), Runnable::run);
    }

    private VectorSearchRequest request() {
        return new VectorSearchRequest(UUID.randomUUID(), UUID.randomUUID(), List.of(0.1f, 0.2f), 10,
                List.of(UUID.randomUUID()));
    }
}
