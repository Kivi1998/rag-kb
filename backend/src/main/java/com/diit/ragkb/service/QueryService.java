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
import com.diit.ragkb.ragcore.intent.QueryIntent;
import com.diit.ragkb.ragcore.intent.QueryIntentClassifier;
import com.diit.ragkb.ragcore.model.Chunk;
import com.diit.ragkb.ragcore.model.Citation;
import com.diit.ragkb.ragcore.model.QueryEvent;
import com.diit.ragkb.ragcore.model.RetrievedChunk;
import com.diit.ragkb.ragcore.quickdocument.QuickDocument;
import com.diit.ragkb.ragcore.quickdocument.QuickDocumentStore;
import com.diit.ragkb.ragcore.rerank.RerankerClient;
import com.diit.ragkb.ragcore.retrieval.RetrievalOptions;
import com.diit.ragkb.ragcore.retrieval.RetrievalResult;
import com.diit.ragkb.ragcore.retrieval.Retriever;
import com.diit.ragkb.repository.KnowledgeDocumentRepository;
import com.diit.ragkb.security.TenantContext;
import org.springframework.beans.factory.ObjectProvider;

import java.util.ArrayList;
import java.util.HashMap;
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

    /**
     * 精确检索型/语义理解型的 RRF 权重倾斜。1.3x/0.7x 是温和倾斜的保守起点，分类器本身
     * 和这组权重都还没有经过真实评估集验证（校准方法参照 {@code MIN_RERANK_SCORE} 的思路：
     * 用 {@code eval/} 对比开关前后 Recall/MRR/拒答F1 确认无回归后再调整）。
     *
     * <p>写成命名常量而非 application.yml 配置项，是为了和本类里其它同样"待验证的检索
     * 调优常量"保持一致的处理方式；调整时需要走代码评审，而不是运维随手改配置——在
     * 这组数字还没有真实数据支撑之前，这是更安全的默认。</p>
     */
    private static final double PRECISE_LOOKUP_BM25_WEIGHT = 1.3;
    private static final double PRECISE_LOOKUP_VECTOR_WEIGHT = 0.7;
    private static final double SEMANTIC_BM25_WEIGHT = 0.7;
    private static final double SEMANTIC_VECTOR_WEIGHT = 1.3;

    private final Retriever retriever;
    private final AnswerGenerator answerGenerator;
    private final KnowledgeBaseService knowledgeBaseService;
    private final KnowledgeDocumentRepository documentRepository;
    private final ObjectProvider<ChatSessionService> chatSessionServiceProvider;
    private final ObjectProvider<ConversationMemoryOrchestrator> memoryOrchestratorProvider;
    private final ObjectProvider<RerankerClient> rerankerProvider;
    private final ObjectProvider<QueryIntentClassifier> intentClassifierProvider;
    private final ObjectProvider<QuickDocumentStore> quickDocumentStoreProvider;

    public QueryService(Retriever retriever, AnswerGenerator answerGenerator, KnowledgeBaseService knowledgeBaseService,
                        KnowledgeDocumentRepository documentRepository,
                        ObjectProvider<ChatSessionService> chatSessionServiceProvider,
                        ObjectProvider<ConversationMemoryOrchestrator> memoryOrchestratorProvider,
                        ObjectProvider<RerankerClient> rerankerProvider,
                        ObjectProvider<QueryIntentClassifier> intentClassifierProvider,
                        ObjectProvider<QuickDocumentStore> quickDocumentStoreProvider) {
        this.retriever = retriever;
        this.answerGenerator = answerGenerator;
        this.knowledgeBaseService = knowledgeBaseService;
        this.documentRepository = documentRepository;
        this.chatSessionServiceProvider = chatSessionServiceProvider;
        this.memoryOrchestratorProvider = memoryOrchestratorProvider;
        this.rerankerProvider = rerankerProvider;
        this.intentClassifierProvider = intentClassifierProvider;
        this.quickDocumentStoreProvider = quickDocumentStoreProvider;
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

        QueryIntentClassifier intentClassifier = intentClassifierProvider.getIfAvailable();
        QueryIntent intent = intentClassifier != null ? intentClassifier.classify(resolvedQuestion) : QueryIntent.UNKNOWN;
        retrievalOptions = applyIntentWeights(retrievalOptions, intent);

        QuickDocumentStore quickDocumentStore = quickDocumentStoreProvider.getIfAvailable();
        Map<UUID, String> quickDocumentNames = new HashMap<>();
        List<RetrievedChunk> quickDocumentChunks = quickDocumentStore == null ? List.of()
                : buildQuickDocumentChunks(quickDocumentStore, sessionId, organizationId, knowledgeBaseId,
                        quickDocumentNames);

        long retrievalStartedAt = System.nanoTime();
        RetrievalResult result = retriever.retrieveWithDecision(organizationId, knowledgeBaseId, resolvedQuestion,
                retrievalOptions);
        long retrievalLatencyMs = elapsedMs(retrievalStartedAt);

        // 会话挂着临时文档时，知识库检索本身触发的拒答阈值不再让整轮问答拒答——只有"检索拒答且
        // 没有临时文档兜底"才真正短路。审计快照必须按这个最终决策记录，不能只看检索的原始结果：
        // 否则临时文档救回的这轮问答会在 rag_query_audit 里被误记成 refused，跟实际生成的真实
        // 回答自相矛盾，误导审计/合规排查。
        boolean actuallyRefused = result.refused() && quickDocumentChunks.isEmpty();
        List<RetrievedChunk> contexts = new ArrayList<>(quickDocumentChunks);
        Map<UUID, String> documentNames = new HashMap<>(quickDocumentNames);
        if (!result.refused()) {
            assertBoundary(result.chunks(), organizationId, knowledgeBaseId);
            contexts.addAll(result.chunks());
            documentNames.putAll(documentRepository
                    .findByKnowledgeBaseIdAndOrgIdOrderByCreatedAtDesc(knowledgeBaseId, organizationId).stream()
                    .collect(java.util.stream.Collectors.toMap(KnowledgeDocument::getId, KnowledgeDocument::getName)));
        }
        QueryAuditSnapshot audit = QueryAuditSnapshot.from(traceId, organizationId, knowledgeBaseId, memberId,
                retrievalLatencyMs, contexts, result.diagnostics(), actuallyRefused,
                actuallyRefused ? result.refusalReason() : null, toAuditLabel(intent));
        if (actuallyRefused) {
            // resolvedQuestion（而非原始 question）才是意图分类实际处理过的文本——训练样本落库
            // 时读的是 resolvedQuestion，两者不一致会让 predicted_intent 标签和存下的文本对不上。
            return PreparedQuery.refused(question, resolvedQuestion, result.refusalReason(), audit);
        }
        if (!quickDocumentChunks.isEmpty()) {
            // 只续期本轮实际用到（即当前仍挂在会话上）的临时文档，未命中的按原 TTL 自然过期。
            quickDocumentStore.touch(sessionId,
                    quickDocumentChunks.stream().map(chunk -> chunk.chunk().documentId()).toList());
        }
        return new PreparedQuery(question, resolvedQuestion, profileContext, organizationId, knowledgeBaseId, memberId,
                sessionId, contexts, CitationBuilder.build(contexts, documentNames), null, audit);
    }

    /**
     * 会话内临时文档（长上下文直接塞入模式）包装成合成 {@link RetrievedChunk}：不经过 BM25/向量
     * 排序，{@code finalScore} 固定设高值让它们排在知识库检索结果前面。{@code nameMapOut} 由
     * 调用方传入并在此填充 docId→文件名，供 {@link CitationBuilder} 复用同一份 Map 查名字。
     */
    private List<RetrievedChunk> buildQuickDocumentChunks(QuickDocumentStore store, UUID sessionId,
                                                           UUID organizationId, UUID knowledgeBaseId,
                                                           Map<UUID, String> nameMapOut) {
        List<QuickDocument> documents = store.findAllBySession(sessionId);
        if (documents.isEmpty()) {
            return List.of();
        }
        List<RetrievedChunk> chunks = new ArrayList<>(documents.size());
        for (QuickDocument document : documents) {
            Chunk chunk = new Chunk("quickdoc:" + document.docId(), organizationId, knowledgeBaseId,
                    document.docId(), 0, document.content(), List.of(), null, null, null, null, "text", null,
                    Map.of("quickDocument", "true"));
            chunks.add(new RetrievedChunk(chunk, null, null, null, null, 1.0));
            nameMapOut.put(document.docId(), document.filename());
        }
        return chunks;
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
                    query.sessionId(), query.question(), answerBuilder.toString(), query.citations());
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

    /**
     * comparative/out-of-scope 分类结果本阶段只记录标签、不调整检索行为（见设计文档）：
     * comparative 的最佳检索策略尚未确定；out-of-scope 若直接短路会绕开已验证过的
     * {@code MIN_RERANK_SCORE} 拒答阈值，改为仅记录，让现有拒答机制照常生效。
     */
    private RetrievalOptions applyIntentWeights(RetrievalOptions options, QueryIntent intent) {
        return switch (intent) {
            case PRECISE_LOOKUP -> options.withWeights(PRECISE_LOOKUP_BM25_WEIGHT, PRECISE_LOOKUP_VECTOR_WEIGHT);
            case SEMANTIC -> options.withWeights(SEMANTIC_BM25_WEIGHT, SEMANTIC_VECTOR_WEIGHT);
            case COMPARATIVE, OUT_OF_SCOPE, UNKNOWN -> options;
        };
    }

    /** UNKNOWN（分类失败/未启用）不写入审计表，其余映射为 prompt 里定义的字面量。 */
    private String toAuditLabel(QueryIntent intent) {
        return switch (intent) {
            case PRECISE_LOOKUP -> "precise-lookup";
            case SEMANTIC -> "semantic";
            case COMPARATIVE -> "comparative";
            case OUT_OF_SCOPE -> "out-of-scope";
            case UNKNOWN -> null;
        };
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

        static PreparedQuery refused(String question, String resolvedQuestion, String reason,
                                     QueryAuditSnapshot audit) {
            return new PreparedQuery(question, resolvedQuestion, null, null, null, null, null, List.of(), List.of(),
                    reason, audit);
        }
    }
}
