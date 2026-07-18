package com.diit.ragkb.service;

import com.diit.ragkb.model.QueryAuditLog;
import com.diit.ragkb.model.QueryAuditStatus;
import com.diit.ragkb.ragcore.audit.QueryAuditSnapshot;
import com.diit.ragkb.ragcore.generation.GenerationMetrics;
import com.diit.ragkb.ragcore.model.Chunk;
import com.diit.ragkb.ragcore.model.RetrievedChunk;
import com.diit.ragkb.ragcore.retrieval.RetrievalDiagnostics;
import com.diit.ragkb.repository.QueryAuditLogRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.List;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

class QueryAuditServiceTest {

    @Test
    void persistsOnlySafeIdentifiersScoresAndUsageWithoutQuestionOrContent() {
        QueryAuditLogRepository repository = mock(QueryAuditLogRepository.class);
        QueryAuditService service = new QueryAuditService(repository, new ObjectMapper());
        UUID orgId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID memberId = UUID.randomUUID();
        UUID documentId = UUID.randomUUID();
        Chunk chunk = new Chunk("chunk-private-id", orgId, kbId, documentId, 0, "机密正文不可落库", List.of(),
                "org/private/path", null, null, null, "markdown", "hash", java.util.Map.of());
        QueryAuditSnapshot snapshot = QueryAuditSnapshot.from("trace-001", orgId, kbId, memberId, 12,
                List.of(new RetrievedChunk(chunk, 1, 1, 0.03, null, 0.92)),
                new RetrievalDiagnostics(3, 4, 5, true, false), false, null, "precise-lookup");

        service.record(snapshot, QueryAuditStatus.COMPLETED, new GenerationMetrics("chat-model", 123, 45, 80),
                34, 46, null);

        ArgumentCaptor<QueryAuditLog> captor = ArgumentCaptor.forClass(QueryAuditLog.class);
        verify(repository).save(captor.capture());
        QueryAuditLog saved = captor.getValue();
        assertEquals("trace-001", saved.getTraceId());
        assertEquals(QueryAuditStatus.COMPLETED, saved.getStatus());
        assertEquals("[\"chunk-private-id\"]", saved.getChunkIdsJson());
        assertEquals("[\"" + documentId + "\"]", saved.getDocumentIdsJson());
        assertEquals("[0.92]", saved.getFinalScoresJson());
        assertEquals("precise-lookup", saved.getPredictedIntent());
        assertEquals(123, saved.getPromptTokens());
        assertEquals(45, saved.getCompletionTokens());
        String persisted = saved.toString();
        assertFalse(persisted.contains("机密正文不可落库"));
        assertFalse(persisted.contains("org/private/path"));
        assertTrue(saved.isEmbeddingFallback());
    }
}
