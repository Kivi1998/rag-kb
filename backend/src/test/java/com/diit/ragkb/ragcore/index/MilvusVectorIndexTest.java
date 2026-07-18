package com.diit.ragkb.ragcore.index;

import com.diit.ragkb.config.RagMilvusProperties;
import com.diit.ragkb.ragcore.model.Chunk;
import io.milvus.v2.client.MilvusClientV2;
import io.milvus.v2.service.vector.request.DeleteReq;
import io.milvus.v2.service.vector.request.QueryReq;
import io.milvus.v2.service.vector.request.UpsertReq;
import io.milvus.v2.service.vector.response.QueryResp;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class MilvusVectorIndexTest {

    @Test
    void stagesInvisibleTenantScopedRows() {
        MilvusClientV2 client = mock(MilvusClientV2.class);
        var index = new MilvusVectorIndex(client, properties());
        Chunk chunk = chunk();

        index.stage(List.of(chunk), List.of(List.of(0.1f, 0.2f)), "bge-m3-v1", "chunk-v1");

        ArgumentCaptor<UpsertReq> captor = ArgumentCaptor.forClass(UpsertReq.class);
        verify(client).upsert(captor.capture());
        var row = captor.getValue().getData().get(0);
        assertEquals(chunk.id(), row.get(MilvusCollectionManager.CHUNK_ID).getAsString());
        assertEquals(chunk.organizationId().toString(), row.get(MilvusCollectionManager.ORG_ID).getAsString());
        assertFalse(row.get(MilvusCollectionManager.RETRIEVAL_READY).getAsBoolean());
        assertEquals(2, row.getAsJsonArray(MilvusCollectionManager.EMBEDDING).size());
    }

    @Test
    void activatesOnlyIdsReturnedByTenantProtectedDocumentQuery() {
        MilvusClientV2 client = mock(MilvusClientV2.class);
        when(client.query(any())).thenReturn(QueryResp.builder().queryResults(List.of(
                QueryResp.QueryResult.builder().entity(Map.of(MilvusCollectionManager.CHUNK_ID, "chunk-1")).build()
        )).build());
        var index = new MilvusVectorIndex(client, properties());
        UUID orgId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID documentId = UUID.randomUUID();

        index.activateDocument(orgId, kbId, documentId);

        ArgumentCaptor<QueryReq> query = ArgumentCaptor.forClass(QueryReq.class);
        verify(client).query(query.capture());
        assertEquals(orgId.toString(), query.getValue().getFilterTemplateValues().get("org_id"));
        assertEquals(kbId.toString(), query.getValue().getFilterTemplateValues().get("kb_id"));
        assertEquals(documentId.toString(), query.getValue().getFilterTemplateValues().get("document_id"));
        ArgumentCaptor<UpsertReq> update = ArgumentCaptor.forClass(UpsertReq.class);
        verify(client).upsert(update.capture());
        assertTrue(update.getValue().isPartialUpdate());
        assertTrue(update.getValue().getData().get(0).get(MilvusCollectionManager.RETRIEVAL_READY).getAsBoolean());
    }

    @Test
    void deleteUsesAllThreeBoundaryFields() {
        MilvusClientV2 client = mock(MilvusClientV2.class);
        var index = new MilvusVectorIndex(client, properties());
        UUID orgId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID documentId = UUID.randomUUID();

        index.deleteByDocumentId(orgId, kbId, documentId);

        ArgumentCaptor<DeleteReq> request = ArgumentCaptor.forClass(DeleteReq.class);
        verify(client).delete(request.capture());
        assertEquals(orgId.toString(), request.getValue().getFilterTemplateValues().get("org_id"));
        assertEquals(kbId.toString(), request.getValue().getFilterTemplateValues().get("kb_id"));
        assertEquals(documentId.toString(), request.getValue().getFilterTemplateValues().get("document_id"));
    }

    @Test
    void rejectsMissingBoundaryAndWrongVectorBeforeSdkCall() {
        MilvusClientV2 client = mock(MilvusClientV2.class);
        var index = new MilvusVectorIndex(client, properties());

        assertThrows(IllegalArgumentException.class,
                () -> index.deleteByDocumentId(null, UUID.randomUUID(), UUID.randomUUID()));
        assertThrows(IllegalArgumentException.class,
                () -> index.stage(List.of(chunk()), List.of(List.of(0.1f)), "model", "chunk-v1"));

        verify(client, never()).delete(any());
        verify(client, never()).upsert(any());
    }

    private Chunk chunk() {
        return new Chunk("chunk-1", UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(), 0,
                "正文", List.of("标题"), "doc.md", 1, 1, 2, "zh", "hash", Map.of());
    }

    private RagMilvusProperties properties() {
        RagMilvusProperties properties = new RagMilvusProperties();
        properties.setEnabled(true);
        properties.setUri("http://localhost:19530");
        properties.setVectorDimensions(2);
        return properties;
    }
}
