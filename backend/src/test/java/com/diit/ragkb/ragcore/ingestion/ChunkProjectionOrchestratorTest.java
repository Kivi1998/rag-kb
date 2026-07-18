package com.diit.ragkb.ragcore.ingestion;

import com.diit.ragkb.ragcore.index.LexicalChunkIndex;
import com.diit.ragkb.ragcore.index.VectorChunkIndex;
import com.diit.ragkb.ragcore.model.Chunk;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;

import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.reset;
import static org.mockito.Mockito.verify;

class ChunkProjectionOrchestratorTest {

    @Test
    void commitsInEsStageMilvusStageMilvusActivateEsActivateOrder() {
        LexicalChunkIndex lexical = mock(LexicalChunkIndex.class);
        VectorChunkIndex vector = mock(VectorChunkIndex.class);
        Chunk chunk = chunk("chunk-1");

        new ChunkProjectionOrchestrator(lexical, vector)
                .project(List.of(chunk), List.of(List.of(0.1f, 0.2f)), "model-v1");

        InOrder order = inOrder(lexical, vector);
        order.verify(lexical).stage(List.of(chunk), List.of(List.of(0.1f, 0.2f)), "model-v1");
        order.verify(vector).stage(List.of(chunk), List.of(List.of(0.1f, 0.2f)), "model-v1", "chunk-v1");
        order.verify(vector).activateDocument(chunk.organizationId(), chunk.knowledgeBaseId(), chunk.documentId());
        order.verify(lexical).activateDocument(chunk.organizationId(), chunk.knowledgeBaseId(), chunk.documentId());
    }

    @Test
    void milvusFailureLeavesEsInvisibleAndRetryConvergesWithSameChunkId() {
        LexicalChunkIndex lexical = mock(LexicalChunkIndex.class);
        VectorChunkIndex vector = mock(VectorChunkIndex.class);
        Chunk chunk = chunk("deterministic-id");
        var orchestrator = new ChunkProjectionOrchestrator(lexical, vector);
        doThrow(new RuntimeException("temporary"))
                .doNothing()
                .when(vector).stage(anyList(), anyList(), anyString(), anyString());

        assertThrows(RuntimeException.class,
                () -> orchestrator.project(List.of(chunk), List.of(List.of(0.1f, 0.2f)), "model-v1"));
        verify(lexical, never()).activateDocument(any(), any(), any());
        verify(vector, never()).activateDocument(any(), any(), any());

        orchestrator.project(List.of(chunk), List.of(List.of(0.1f, 0.2f)), "model-v1");

        verify(vector).activateDocument(chunk.organizationId(), chunk.knowledgeBaseId(), chunk.documentId());
        verify(lexical).activateDocument(chunk.organizationId(), chunk.knowledgeBaseId(), chunk.documentId());
    }

    @Test
    void rejectsMixedTenantBatchBeforeAnyWrite() {
        LexicalChunkIndex lexical = mock(LexicalChunkIndex.class);
        VectorChunkIndex vector = mock(VectorChunkIndex.class);
        Chunk first = chunk("one");
        Chunk second = new Chunk("two", UUID.randomUUID(), first.knowledgeBaseId(), first.documentId(), 1,
                "正文", List.of(), "doc.md", null, null, null, "zh", "hash", Map.of());

        assertThrows(IllegalArgumentException.class, () -> new ChunkProjectionOrchestrator(lexical, vector)
                .project(List.of(first, second), List.of(List.of(0.1f), List.of(0.2f)), "model-v1"));

        verify(lexical, never()).stage(anyList(), anyList(), anyString());
        verify(vector, never()).stage(anyList(), anyList(), anyString(), anyString());
    }

    private Chunk chunk(String id) {
        return new Chunk(id, UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(), 0,
                "正文", List.of(), "doc.md", null, null, null, "zh", "hash",
                Map.of("chunkVersion", "chunk-v1"));
    }
}
