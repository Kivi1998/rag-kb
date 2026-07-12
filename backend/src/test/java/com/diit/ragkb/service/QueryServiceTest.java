package com.diit.ragkb.service;

import com.diit.ragkb.model.KnowledgeBase;
import com.diit.ragkb.model.KnowledgeDocument;
import com.diit.ragkb.ragcore.generation.AnswerGenerator;
import com.diit.ragkb.ragcore.model.Chunk;
import com.diit.ragkb.ragcore.model.QueryEvent;
import com.diit.ragkb.ragcore.model.RetrievedChunk;
import com.diit.ragkb.ragcore.retrieval.RetrievalOptions;
import com.diit.ragkb.ragcore.retrieval.RetrievalResult;
import com.diit.ragkb.ragcore.retrieval.Retriever;
import com.diit.ragkb.repository.KnowledgeDocumentRepository;
import com.diit.ragkb.security.TenantContext;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
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

class QueryServiceTest {

    @AfterEach
    void clearTenant() {
        TenantContext.clear();
    }

    @Test
    void emitsServerBuiltSourceBeforeGenerationAndNeverLeaksStoragePath() {
        UUID orgId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID documentId = UUID.randomUUID();
        TenantContext.set(orgId, UUID.randomUUID(), "MEMBER");
        KnowledgeBaseService kbService = mock(KnowledgeBaseService.class);
        when(kbService.getByIdAndCurrentOrg(kbId)).thenReturn(new KnowledgeBase());
        KnowledgeDocument document = new KnowledgeDocument();
        document.setId(documentId);
        document.setName("部署手册.md");
        KnowledgeDocumentRepository documents = mock(KnowledgeDocumentRepository.class);
        when(documents.findByKnowledgeBaseIdAndOrgIdOrderByCreatedAtDesc(kbId, orgId)).thenReturn(List.of(document));
        RetrievedChunk retrieved = retrieved(orgId, kbId, documentId);
        Retriever retriever = retriever(new RetrievalResult(List.of(retrieved), null));
        AnswerGenerator generator = (question, contexts, consumer) -> consumer.accept(QueryEvent.chunk("请检查数据库连接。"));
        QueryService service = new QueryService(retriever, generator, kbService, documents);

        QueryService.PreparedQuery prepared = service.prepare(kbId, "如何排查启动失败？");
        List<QueryEvent> events = new ArrayList<>();
        service.stream(prepared, events::add);

        assertEquals(2, events.size());
        assertEquals("source", events.get(0).sseEventName());
        assertEquals("部署手册.md", events.get(0).citation().documentName());
        assertTrue(!events.get(0).citation().documentName().contains("org/"));
        assertEquals("chunk", events.get(1).sseEventName());
    }

    @Test
    void refusalDoesNotCallGeneration() {
        UUID orgId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        TenantContext.set(orgId, UUID.randomUUID(), "MEMBER");
        KnowledgeBaseService kbService = mock(KnowledgeBaseService.class);
        when(kbService.getByIdAndCurrentOrg(kbId)).thenReturn(new KnowledgeBase());
        KnowledgeDocumentRepository documents = mock(KnowledgeDocumentRepository.class);
        AnswerGenerator generator = mock(AnswerGenerator.class);
        QueryService service = new QueryService(retriever(RetrievalResult.refuse("未在当前知识库中检索到足够依据")),
                generator, kbService, documents);

        List<QueryEvent> events = new ArrayList<>();
        service.stream(service.prepare(kbId, "不存在的问题"), events::add);

        assertEquals(List.of("refusal"), events.stream().map(QueryEvent::sseEventName).toList());
        verify(generator, never()).stream(any(), any(), any());
        verify(documents, never()).findByKnowledgeBaseIdAndOrgIdOrderByCreatedAtDesc(any(), any());
    }

    @Test
    void rejectsCrossTenantOrCrossKnowledgeBaseCandidateBeforeItCanBecomeCitation() {
        UUID orgId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        TenantContext.set(orgId, UUID.randomUUID(), "MEMBER");
        KnowledgeBaseService kbService = mock(KnowledgeBaseService.class);
        when(kbService.getByIdAndCurrentOrg(kbId)).thenReturn(new KnowledgeBase());
        KnowledgeDocumentRepository documents = mock(KnowledgeDocumentRepository.class);
        RetrievedChunk wrongTenant = retrieved(UUID.randomUUID(), kbId, UUID.randomUUID());
        QueryService service = new QueryService(retriever(new RetrievalResult(List.of(wrongTenant), null)),
                mock(AnswerGenerator.class), kbService, documents);

        assertThrows(IllegalStateException.class, () -> service.prepare(kbId, "查询"));
        verify(documents, never()).findByKnowledgeBaseIdAndOrgIdOrderByCreatedAtDesc(any(), any());
    }

    private Retriever retriever(RetrievalResult result) {
        return new Retriever() {
            @Override public List<RetrievedChunk> retrieve(UUID organizationId, UUID knowledgeBaseId, String query,
                                                            RetrievalOptions options) {
                return result.chunks();
            }
            @Override public RetrievalResult retrieveWithDecision(UUID organizationId, UUID knowledgeBaseId, String query,
                                                                   RetrievalOptions options) {
                return result;
            }
        };
    }

    private RetrievedChunk retrieved(UUID orgId, UUID kbId, UUID documentId) {
        Chunk chunk = new Chunk("chunk-1", orgId, kbId, documentId, 0, "数据库连接失败时检查 JDBC URL。",
                List.of("部署", "数据库"), "org/private/object.md", 3, 11, 12, "markdown", "hash", java.util.Map.of());
        return new RetrievedChunk(chunk, 1, 1, 0.032, 0.9, 0.9);
    }
}
