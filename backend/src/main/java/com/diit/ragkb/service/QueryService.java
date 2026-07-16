package com.diit.ragkb.service;

import com.diit.ragkb.model.KnowledgeDocument;
import com.diit.ragkb.ragcore.audit.QueryAuditSnapshot;
import com.diit.ragkb.ragcore.conversation.ConversationMemoryOrchestrator;
import com.diit.ragkb.ragcore.conversation.MemoryContext;
import com.diit.ragkb.ragcore.generation.AnswerGenerator;
import com.diit.ragkb.ragcore.generation.AnswerSelfChecker;
import com.diit.ragkb.ragcore.generation.CitationBuilder;
import com.diit.ragkb.ragcore.generation.FactVerificationGate;
import com.diit.ragkb.ragcore.generation.GenerationMetrics;
import com.diit.ragkb.ragcore.generation.SelfCheckResult;
import com.diit.ragkb.ragcore.model.Citation;
import com.diit.ragkb.ragcore.model.QueryEvent;
import com.diit.ragkb.ragcore.model.RetrievedChunk;
import com.diit.ragkb.ragcore.rerank.RerankerClient;
import com.diit.ragkb.ragcore.retrieval.RetrievalOptions;
import com.diit.ragkb.ragcore.retrieval.RetrievalResult;
import com.diit.ragkb.ragcore.retrieval.Retriever;
import com.diit.ragkb.repository.KnowledgeDocumentRepository;
import com.diit.ragkb.security.TenantContext;
import org.springframework.beans.factory.ObjectProvider;

import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Consumer;

/**
 * 问答应用服务：在 HTTP 线程完成租户校验和检索，在 SSE 线程仅消费不可变查询快照。
 *
 * <p>会话记忆是可选增强（{@code rag.memory.enabled=false} 时 {@code memoryOrchestratorProvider}/
 * {@code chatSessionServiceProvider} 均取不到 bean），退化为原先的无记忆单轮问答，不影响主链路。</p>
 */
public class QueryService {

    private final Retriever retriever;
    private final AnswerGenerator answerGenerator;
    private final KnowledgeBaseService knowledgeBaseService;
    private final KnowledgeDocumentRepository documentRepository;
    private final ObjectProvider<ChatSessionService> chatSessionServiceProvider;
    private final ObjectProvider<ConversationMemoryOrchestrator> memoryOrchestratorProvider;
    private final ObjectProvider<RerankerClient> rerankerProvider;

    public QueryService(Retriever retriever, AnswerGenerator answerGenerator, KnowledgeBaseService knowledgeBaseService,
                        KnowledgeDocumentRepository documentRepository,
                        ObjectProvider<ChatSessionService> chatSessionServiceProvider,
                        ObjectProvider<ConversationMemoryOrchestrator> memoryOrchestratorProvider,
                        ObjectProvider<RerankerClient> rerankerProvider) {
        this.retriever = retriever;
        this.answerGenerator = answerGenerator;
        this.knowledgeBaseService = knowledgeBaseService;
        this.documentRepository = documentRepository;
        this.chatSessionServiceProvider = chatSessionServiceProvider;
        this.memoryOrchestratorProvider = memoryOrchestratorProvider;
        this.rerankerProvider = rerankerProvider;
    }

    public PreparedQuery prepare(UUID knowledgeBaseId, UUID sessionId, String question) {
        return prepare(knowledgeBaseId, sessionId, question, UUID.randomUUID().toString());
    }

    public PreparedQuery prepare(UUID knowledgeBaseId, UUID sessionId, String question, String traceId) {
        // 先按当前 ThreadLocal 租户验证 kb，异步线程不再读取 TenantContext。
        knowledgeBaseService.getByIdAndCurrentOrg(knowledgeBaseId);
        UUID organizationId = requireOrganizationId();
        UUID memberId = requireMemberId();

        ChatSessionService chatSessionService = chatSessionServiceProvider.getIfAvailable();
        if (chatSessionService != null) {
            chatSessionService.touchSession(knowledgeBaseId, sessionId); // 校验归属并续期，越权/不存在 → 抛异常映射 404
        }

        String resolvedQuestion = question;
        String profileContext = null;
        RetrievalOptions retrievalOptions = RetrievalOptions.defaults();
        ConversationMemoryOrchestrator orchestrator = memoryOrchestratorProvider.getIfAvailable();
        if (orchestrator != null) {
            MemoryContext memoryContext = orchestrator.prepareContext(organizationId, memberId, sessionId, question);
            resolvedQuestion = memoryContext.resolvedQuestion();
            profileContext = memoryContext.hasProfileContext() ? memoryContext.profileSystemContext() : null;
            if (memoryContext.resolvedQuestionVector() != null) {
                // 复用记忆子系统已经算好的 resolvedQuestion 向量，避免检索阶段重复调用 Embedding。
                retrievalOptions = retrievalOptions.withPrecomputedQueryVector(memoryContext.resolvedQuestionVector());
            }
        }

        long retrievalStartedAt = System.nanoTime();
        RetrievalResult result = retriever.retrieveWithDecision(organizationId, knowledgeBaseId, resolvedQuestion,
                retrievalOptions);
        long retrievalLatencyMs = elapsedMs(retrievalStartedAt);
        QueryAuditSnapshot audit = QueryAuditSnapshot.from(traceId, organizationId, knowledgeBaseId, memberId,
                retrievalLatencyMs, result.chunks(), result.diagnostics(), result.refused(), result.refusalReason());
        if (result.refused()) {
            return PreparedQuery.refused(question, result.refusalReason(), audit);
        }
        assertBoundary(result.chunks(), organizationId, knowledgeBaseId);
        Map<UUID, String> documentNames = documentRepository
                .findByKnowledgeBaseIdAndOrgIdOrderByCreatedAtDesc(knowledgeBaseId, organizationId).stream()
                .collect(java.util.stream.Collectors.toMap(KnowledgeDocument::getId, KnowledgeDocument::getName));
        return new PreparedQuery(question, resolvedQuestion, profileContext, organizationId, knowledgeBaseId, memberId,
                sessionId, result.chunks(), CitationBuilder.build(result.chunks(), documentNames), null, audit);
    }

    public GenerationMetrics stream(PreparedQuery query, Consumer<QueryEvent> eventConsumer) {
        if (query.refusalReason() != null) {
            eventConsumer.accept(QueryEvent.refusal(query.refusalReason()));
            return GenerationMetrics.none();
        }
        StringBuilder answerBuilder = new StringBuilder();
        FactVerificationGate gate = new FactVerificationGate(query.citations(), event -> {
            if (event.content() != null) answerBuilder.append(event.content());
            eventConsumer.accept(event);
        });
        GenerationMetrics rawMetrics = answerGenerator.streamWithMetrics(query.resolvedQuestion(), query.contexts(),
                query.profileContext(), gate.asConsumer());
        gate.flush(); // 模型可能整段输出就是判断行本身，流结束时仍需收尾解析一次缓冲区。
        GenerationMetrics metrics = gate.refusedByFactVerification()
                ? rawMetrics.withFactVerificationRefusalReason("NO_RETRIEVAL")
                : rawMetrics;
        if (!gate.refusedByFactVerification()) {
            runSelfCheck(answerBuilder.toString(), query.citations(), eventConsumer);
        }
        ChatSessionService chatSessionService = chatSessionServiceProvider.getIfAvailable();
        if (chatSessionService != null) {
            // 会话标题只依赖问题文本，与本轮是否被事实核验拒答无关（纯 Postgres 关注点）。
            chatSessionService.maybeSetTitle(query.organizationId(), query.knowledgeBaseId(), query.memberId(),
                    query.sessionId(), query.question());
        }
        ConversationMemoryOrchestrator orchestrator = memoryOrchestratorProvider.getIfAvailable();
        if (orchestrator != null && !gate.refusedByFactVerification()) {
            // 事实核验拒答没有产生真实回答，与检索阶段拒答一致，不计入会话记忆（避免记一条空答案）。
            orchestrator.recordTurn(query.organizationId(), query.knowledgeBaseId(), query.memberId(),
                    query.sessionId(), query.question(), answerBuilder.toString());
        }
        return metrics;
    }

    /**
     * 生成后自检：独立于生成模型之外，核查正文是否有资料支撑；不影响审计状态与会话记忆，
     * 只是附加的质量提醒。Reranker 未配置时直接跳过（fail-open，与 Reranker 调用异常时的行为一致）。
     */
    private void runSelfCheck(String answerText, List<Citation> citations, Consumer<QueryEvent> eventConsumer) {
        RerankerClient reranker = rerankerProvider.getIfAvailable();
        if (reranker == null) {
            return;
        }
        SelfCheckResult result = new AnswerSelfChecker(reranker).check(answerText, citations);
        if (result.hasUnsupportedClaims()) {
            eventConsumer.accept(QueryEvent.selfCheckWarning(result.buildWarningMessage()));
        }
    }

    private UUID requireOrganizationId() {
        UUID organizationId = TenantContext.getOrgId();
        if (organizationId == null) throw new IllegalStateException("缺少租户上下文");
        return organizationId;
    }

    private UUID requireMemberId() {
        UUID memberId = TenantContext.getMemberId();
        if (memberId == null) throw new IllegalStateException("缺少成员上下文");
        return memberId;
    }

    private long elapsedMs(long startedAtNanos) {
        return java.util.concurrent.TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - startedAtNanos);
    }

    private void assertBoundary(List<RetrievedChunk> chunks, UUID organizationId, UUID knowledgeBaseId) {
        boolean invalid = chunks.stream().anyMatch(item -> !organizationId.equals(item.chunk().organizationId())
                || !knowledgeBaseId.equals(item.chunk().knowledgeBaseId()));
        if (invalid) throw new IllegalStateException("检索结果越过组织或知识库边界");
    }

    public record PreparedQuery(String question, String resolvedQuestion, String profileContext,
                                UUID organizationId, UUID knowledgeBaseId, UUID memberId, UUID sessionId,
                                List<RetrievedChunk> contexts, List<Citation> citations, String refusalReason,
                                QueryAuditSnapshot audit) {
        public PreparedQuery {
            contexts = contexts == null ? List.of() : List.copyOf(contexts);
            citations = citations == null ? List.of() : List.copyOf(citations);
        }

        static PreparedQuery refused(String question, String reason, QueryAuditSnapshot audit) {
            return new PreparedQuery(question, question, null, null, null, null, null, List.of(), List.of(), reason,
                    audit);
        }
    }
}
