package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.config.RagMilvusProperties;
import io.milvus.v2.client.MilvusClientV2;
import io.milvus.v2.service.vector.request.SearchReq;
import io.milvus.v2.service.vector.response.SearchResp;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.List;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class MilvusVectorCandidateSourceTest {

    @Test
    void searchesWithTenantVisibilityDocumentAndEfFilters() {
        MilvusClientV2 client = mock(MilvusClientV2.class);
        when(client.search(any())).thenReturn(SearchResp.builder().searchResults(List.of(List.of(
                SearchResp.SearchResult.builder().primaryKey("chunk-1").score(0.91f).build(),
                SearchResp.SearchResult.builder().id("chunk-2").score(0.82f).build()
        ))).build());
        var source = new MilvusVectorCandidateSource(client, properties());
        UUID orgId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID documentId = UUID.randomUUID();

        List<VectorHit> result = source.search(new VectorSearchRequest(orgId, kbId,
                List.of(0.1f, 0.2f), 30, List.of(documentId)));

        assertEquals(List.of(new VectorHit("chunk-1", 1, 0.91f),
                new VectorHit("chunk-2", 2, 0.82f)), result);
        ArgumentCaptor<SearchReq> request = ArgumentCaptor.forClass(SearchReq.class);
        verify(client).search(request.capture());
        assertTrue(request.getValue().getFilter().contains("retrieval_ready == true"));
        assertTrue(request.getValue().getFilter().contains("document_id in {document_ids}"));
        assertEquals(orgId.toString(), request.getValue().getFilterTemplateValues().get("org_id"));
        assertEquals(kbId.toString(), request.getValue().getFilterTemplateValues().get("kb_id"));
        assertEquals(List.of(documentId.toString()), request.getValue().getFilterTemplateValues().get("document_ids"));
        assertEquals(128, request.getValue().getSearchParams().get("ef"));
    }

    @Test
    void rejectsWrongDimensionsBeforeSdkCall() {
        MilvusClientV2 client = mock(MilvusClientV2.class);
        var source = new MilvusVectorCandidateSource(client, properties());

        assertThrows(IllegalArgumentException.class, () -> source.search(new VectorSearchRequest(
                UUID.randomUUID(), UUID.randomUUID(), List.of(0.1f), 10)));

        verify(client, never()).search(any());
    }

    private RagMilvusProperties properties() {
        RagMilvusProperties properties = new RagMilvusProperties();
        properties.setEnabled(true);
        properties.setUri("http://localhost:19530");
        properties.setVectorDimensions(2);
        return properties;
    }
}
