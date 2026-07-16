package com.diit.ragkb.service;

import com.diit.ragkb.model.KnowledgeBase;
import com.diit.ragkb.model.KnowledgeDocument;
import com.diit.ragkb.ragcore.conversation.ConversationMemoryOrchestrator;
import com.diit.ragkb.ragcore.generation.AnswerGenerator;
import com.diit.ragkb.ragcore.generation.GenerationMetrics;
import com.diit.ragkb.ragcore.model.Chunk;
import com.diit.ragkb.ragcore.model.QueryEvent;
import com.diit.ragkb.ragcore.model.RetrievedChunk;
import com.diit.ragkb.ragcore.rerank.RerankerClient;
import com.diit.ragkb.ragcore.retrieval.RetrievalOptions;
import com.diit.ragkb.ragcore.retrieval.RetrievalResult;
import com.diit.ragkb.ragcore.retrieval.Retriever;
import com.diit.ragkb.repository.KnowledgeDocumentRepository;
import com.diit.ragkb.security.TenantContext;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
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
        QueryService service = new QueryService(retriever, generator, kbService, documents, emptyProvider(),
                emptyProvider(), emptyProvider());

        QueryService.PreparedQuery prepared = service.prepare(kbId, UUID.randomUUID(), "如何排查启动失败？");
        List<QueryEvent> events = new ArrayList<>();
        GenerationMetrics metrics = service.stream(prepared, events::add);

        assertEquals(2, events.size());
        assertEquals("source", events.get(0).sseEventName());
        assertEquals("部署手册.md", events.get(0).citation().documentName());
        assertTrue(!events.get(0).citation().documentName().contains("org/"));
        assertEquals("chunk", events.get(1).sseEventName());
        assertEquals("unknown", metrics.model());
        assertEquals(9, metrics.outputCharacters());
        assertTrue(!prepared.audit().chunkIds().isEmpty());
        assertTrue(!prepared.audit().toString().contains("如何排查启动失败"));
        assertTrue(!prepared.audit().toString().contains("数据库连接失败"));
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
                generator, kbService, documents, emptyProvider(), emptyProvider(), emptyProvider());

        List<QueryEvent> events = new ArrayList<>();
        QueryService.PreparedQuery prepared = service.prepare(kbId, UUID.randomUUID(), "不存在的问题");
        GenerationMetrics metrics = service.stream(prepared, events::add);

        assertEquals(List.of("refusal"), events.stream().map(QueryEvent::sseEventName).toList());
        verify(generator, never()).stream(any(), any(), any());
        verify(documents, never()).findByKnowledgeBaseIdAndOrgIdOrderByCreatedAtDesc(any(), any());
        assertEquals("none", metrics.model());
        assertTrue(prepared.audit().refused());
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
                mock(AnswerGenerator.class), kbService, documents, emptyProvider(), emptyProvider(), emptyProvider());

        assertThrows(IllegalStateException.class, () -> service.prepare(kbId, UUID.randomUUID(), "查询"));
        verify(documents, never()).findByKnowledgeBaseIdAndOrgIdOrderByCreatedAtDesc(any(), any());
    }

    @Test
    void touchesSessionWhenMemoryFeatureEnabled() {
        UUID orgId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID sessionId = UUID.randomUUID();
        TenantContext.set(orgId, UUID.randomUUID(), "MEMBER");
        KnowledgeBaseService kbService = mock(KnowledgeBaseService.class);
        when(kbService.getByIdAndCurrentOrg(kbId)).thenReturn(new KnowledgeBase());
        KnowledgeDocumentRepository documents = mock(KnowledgeDocumentRepository.class);
        ChatSessionService chatSessionService = mock(ChatSessionService.class);
        ObjectProvider<ChatSessionService> sessionProvider = mock(ObjectProvider.class);
        when(sessionProvider.getIfAvailable()).thenReturn(chatSessionService);
        QueryService service = new QueryService(retriever(RetrievalResult.refuse("拒答")), mock(AnswerGenerator.class),
                kbService, documents, sessionProvider, emptyProvider(), emptyProvider());

        service.prepare(kbId, sessionId, "问题");

        verify(chatSessionService, org.mockito.Mockito.times(1)).touchSession(kbId, sessionId);
    }

    @Test
    void invalidSessionPropagatesExceptionBeforeRetrieval() {
        UUID orgId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID sessionId = UUID.randomUUID();
        TenantContext.set(orgId, UUID.randomUUID(), "MEMBER");
        KnowledgeBaseService kbService = mock(KnowledgeBaseService.class);
        when(kbService.getByIdAndCurrentOrg(kbId)).thenReturn(new KnowledgeBase());
        KnowledgeDocumentRepository documents = mock(KnowledgeDocumentRepository.class);
        ChatSessionService chatSessionService = mock(ChatSessionService.class);
        when(chatSessionService.touchSession(kbId, sessionId))
                .thenThrow(new com.diit.ragkb.exception.ResourceNotFoundException("会话不存在"));
        ObjectProvider<ChatSessionService> sessionProvider = mock(ObjectProvider.class);
        when(sessionProvider.getIfAvailable()).thenReturn(chatSessionService);
        Retriever retriever = mock(Retriever.class);
        QueryService service = new QueryService(retriever, mock(AnswerGenerator.class), kbService, documents,
                sessionProvider, emptyProvider(), emptyProvider());

        assertThrows(com.diit.ragkb.exception.ResourceNotFoundException.class,
                () -> service.prepare(kbId, sessionId, "问题"));
        verify(retriever, never()).retrieveWithDecision(any(), any(), any(), any());
    }

    @Test
    void memoryOrchestratorResolvesQuestionAndInjectsProfileIntoGeneration() {
        UUID orgId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID documentId = UUID.randomUUID();
        UUID sessionId = UUID.randomUUID();
        TenantContext.set(orgId, UUID.randomUUID(), "MEMBER");
        KnowledgeBaseService kbService = mock(KnowledgeBaseService.class);
        when(kbService.getByIdAndCurrentOrg(kbId)).thenReturn(new KnowledgeBase());
        KnowledgeDocument document = new KnowledgeDocument();
        document.setId(documentId);
        document.setName("文档.md");
        KnowledgeDocumentRepository documents = mock(KnowledgeDocumentRepository.class);
        when(documents.findByKnowledgeBaseIdAndOrgIdOrderByCreatedAtDesc(kbId, orgId)).thenReturn(List.of(document));

        ConversationMemoryOrchestrator orchestrator = mock(ConversationMemoryOrchestrator.class);
        com.diit.ragkb.ragcore.conversation.MemoryContext memoryContext =
                new com.diit.ragkb.ragcore.conversation.MemoryContext("重疾险犹豫期过了还能退保吗", "用户偏好：常问保险条款", null);
        when(orchestrator.prepareContext(eq(orgId), any(), eq(sessionId), eq("那它呢"))).thenReturn(memoryContext);
        ObjectProvider<ConversationMemoryOrchestrator> orchestratorProvider = mock(ObjectProvider.class);
        when(orchestratorProvider.getIfAvailable()).thenReturn(orchestrator);

        Retriever retriever = mock(Retriever.class);
        RetrievedChunk retrieved = retrieved(orgId, kbId, documentId);
        when(retriever.retrieveWithDecision(eq(orgId), eq(kbId), eq("重疾险犹豫期过了还能退保吗"), any()))
                .thenReturn(new RetrievalResult(List.of(retrieved), null));

        List<String> capturedSystemContext = new ArrayList<>();
        AnswerGenerator generator = new AnswerGenerator() {
            @Override
            public void stream(String question, List<RetrievedChunk> contexts, java.util.function.Consumer<QueryEvent> c) { }

            @Override
            public GenerationMetrics streamWithMetrics(String question, List<RetrievedChunk> contexts,
                                                       String additionalSystemContext,
                                                       java.util.function.Consumer<QueryEvent> eventConsumer) {
                capturedSystemContext.add(additionalSystemContext);
                eventConsumer.accept(QueryEvent.chunk("答案"));
                return GenerationMetrics.none();
            }
        };
        QueryService service = new QueryService(retriever, generator, kbService, documents, emptyProvider(),
                orchestratorProvider, emptyProvider());

        QueryService.PreparedQuery prepared = service.prepare(kbId, sessionId, "那它呢");
        service.stream(prepared, e -> { });

        verify(retriever, org.mockito.Mockito.times(1))
                .retrieveWithDecision(eq(orgId), eq(kbId), eq("重疾险犹豫期过了还能退保吗"), any());
        assertEquals(List.of("用户偏好：常问保险条款"), capturedSystemContext);
        verify(orchestrator, org.mockito.Mockito.times(1)).recordTurn(eq(orgId), eq(kbId), any(), eq(sessionId),
                eq("那它呢"), eq("答案"));
    }

    @Test
    void reusesMemoryOrchestratorVectorInsteadOfLettingRetrieverEmbedAgain() {
        // 回归测试：记忆子系统已经算出 resolvedQuestion 向量时，应该把它带给检索阶段复用，
        // 而不是让 QueryService 对同一句话让检索链路再调用一次 Embedding。
        UUID orgId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID sessionId = UUID.randomUUID();
        TenantContext.set(orgId, UUID.randomUUID(), "MEMBER");
        KnowledgeBaseService kbService = mock(KnowledgeBaseService.class);
        when(kbService.getByIdAndCurrentOrg(kbId)).thenReturn(new KnowledgeBase());
        KnowledgeDocumentRepository documents = mock(KnowledgeDocumentRepository.class);

        List<Float> precomputedVector = List.of(0.5f, 0.6f);
        ConversationMemoryOrchestrator orchestrator = mock(ConversationMemoryOrchestrator.class);
        com.diit.ragkb.ragcore.conversation.MemoryContext memoryContext =
                new com.diit.ragkb.ragcore.conversation.MemoryContext("重疾险犹豫期过了还能退保吗", "", precomputedVector);
        when(orchestrator.prepareContext(eq(orgId), any(), eq(sessionId), any())).thenReturn(memoryContext);
        ObjectProvider<ConversationMemoryOrchestrator> orchestratorProvider = mock(ObjectProvider.class);
        when(orchestratorProvider.getIfAvailable()).thenReturn(orchestrator);

        Retriever retriever = mock(Retriever.class);
        when(retriever.retrieveWithDecision(any(), any(), any(), any()))
                .thenReturn(RetrievalResult.refuse("拒答"));
        QueryService service = new QueryService(retriever, mock(AnswerGenerator.class), kbService, documents,
                emptyProvider(), orchestratorProvider, emptyProvider());

        service.prepare(kbId, sessionId, "那它呢");

        org.mockito.ArgumentCaptor<com.diit.ragkb.ragcore.retrieval.RetrievalOptions> optionsCaptor =
                org.mockito.ArgumentCaptor.forClass(com.diit.ragkb.ragcore.retrieval.RetrievalOptions.class);
        verify(retriever).retrieveWithDecision(eq(orgId), eq(kbId), eq("重疾险犹豫期过了还能退保吗"),
                optionsCaptor.capture());
        assertEquals(precomputedVector, optionsCaptor.getValue().precomputedQueryVector());
    }

    @Test
    void factVerificationRefusalDoesNotEmitSourceAndSkipsMemoryRecording() {
        UUID orgId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID documentId = UUID.randomUUID();
        UUID sessionId = UUID.randomUUID();
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
        AnswerGenerator generator = (question, contexts, consumer) ->
                consumer.accept(QueryEvent.chunk("{\"found\": false}"));

        ConversationMemoryOrchestrator orchestrator = mock(ConversationMemoryOrchestrator.class);
        when(orchestrator.prepareContext(eq(orgId), any(), eq(sessionId), eq("随机数种子设的多少？")))
                .thenReturn(new com.diit.ragkb.ragcore.conversation.MemoryContext("随机数种子设的多少？", null, null));
        ObjectProvider<ConversationMemoryOrchestrator> orchestratorProvider = mock(ObjectProvider.class);
        when(orchestratorProvider.getIfAvailable()).thenReturn(orchestrator);
        QueryService service = new QueryService(retriever, generator, kbService, documents, emptyProvider(),
                orchestratorProvider, emptyProvider());

        QueryService.PreparedQuery prepared = service.prepare(kbId, sessionId, "随机数种子设的多少？");
        List<QueryEvent> events = new ArrayList<>();
        GenerationMetrics metrics = service.stream(prepared, events::add);

        assertEquals(List.of("refusal"), events.stream().map(QueryEvent::sseEventName).toList());
        assertEquals("未在当前知识库中检索到该问题的具体答案", events.get(0).message());
        assertEquals("NO_RETRIEVAL", metrics.factVerificationRefusalReason());
        verify(orchestrator, never()).recordTurn(any(), any(), any(), any(), any(), any());
    }

    @Test
    void selfCheckEmitsWarningWhenAnswerHasUnsupportedClaim() {
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
        AnswerGenerator generator = (question, contexts, consumer) ->
                consumer.accept(QueryEvent.chunk("{\"found\": true}\n这是一句没有任何引用标记的实质性陈述句。"));
        RerankerClient reranker = mock(RerankerClient.class);
        ObjectProvider<RerankerClient> rerankerProvider = mock(ObjectProvider.class);
        when(rerankerProvider.getIfAvailable()).thenReturn(reranker);
        QueryService service = new QueryService(retriever, generator, kbService, documents, emptyProvider(),
                emptyProvider(), rerankerProvider);

        QueryService.PreparedQuery prepared = service.prepare(kbId, UUID.randomUUID(), "如何排查启动失败？");
        List<QueryEvent> events = new ArrayList<>();
        service.stream(prepared, events::add);

        assertTrue(events.stream().anyMatch(e -> e.sseEventName().equals("self_check_warning")));
    }

    @Test
    void selfCheckSkipsWarningWhenAnswerIsWellSupported() {
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
        AnswerGenerator generator = (question, contexts, consumer) ->
                consumer.accept(QueryEvent.chunk("{\"found\": true}\n请检查 JDBC URL [资料1]。"));
        RerankerClient reranker = (query, candidates, topK) -> candidates.stream()
                .map(c -> new RetrievedChunk(c.chunk(), c.bm25Rank(), c.vectorRank(), c.rrfScore(), 0.9, 0.9))
                .toList();
        ObjectProvider<RerankerClient> rerankerProvider = mock(ObjectProvider.class);
        when(rerankerProvider.getIfAvailable()).thenReturn(reranker);
        QueryService service = new QueryService(retriever, generator, kbService, documents, emptyProvider(),
                emptyProvider(), rerankerProvider);

        QueryService.PreparedQuery prepared = service.prepare(kbId, UUID.randomUUID(), "如何排查启动失败？");
        List<QueryEvent> events = new ArrayList<>();
        service.stream(prepared, events::add);

        assertTrue(events.stream().noneMatch(e -> e.sseEventName().equals("self_check_warning")));
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

    /** 模拟 rag.memory.enabled=false 时的 Bean 缺失场景：ObjectProvider 取不到任何实例。 */
    @SuppressWarnings("unchecked")
    private <T> ObjectProvider<T> emptyProvider() {
        ObjectProvider<T> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(null);
        return provider;
    }
}
