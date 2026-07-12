package com.diit.ragkb.service;

import com.diit.ragkb.model.KnowledgeDocument;
import com.diit.ragkb.ragcore.audit.QueryAuditSnapshot;
import com.diit.ragkb.ragcore.generation.AnswerGenerator;
import com.diit.ragkb.ragcore.generation.CitationBuilder;
import com.diit.ragkb.ragcore.generation.GenerationMetrics;
import com.diit.ragkb.ragcore.model.Citation;
import com.diit.ragkb.ragcore.model.QueryEvent;
import com.diit.ragkb.ragcore.model.RetrievedChunk;
import com.diit.ragkb.ragcore.retrieval.RetrievalOptions;
import com.diit.ragkb.ragcore.retrieval.RetrievalResult;
import com.diit.ragkb.ragcore.retrieval.Retriever;
import com.diit.ragkb.repository.KnowledgeDocumentRepository;
import com.diit.ragkb.security.TenantContext;

import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Consumer;

/**
 * 问答应用服务：在 HTTP 线程完成租户校验和检索，在 SSE 线程仅消费不可变查询快照。
 */
public class QueryService {

    private final Retriever retriever;
    private final AnswerGenerator answerGenerator;
    private final KnowledgeBaseService knowledgeBaseService;
    private final KnowledgeDocumentRepository documentRepository;

    public QueryService(Retriever retriever, AnswerGenerator answerGenerator, KnowledgeBaseService knowledgeBaseService,
                        KnowledgeDocumentRepository documentRepository) {
        this.retriever = retriever;
        this.answerGenerator = answerGenerator;
        this.knowledgeBaseService = knowledgeBaseService;
        this.documentRepository = documentRepository;
    }

    public PreparedQuery prepare(UUID knowledgeBaseId, String question) {
        return prepare(knowledgeBaseId, question, UUID.randomUUID().toString());
    }

    public PreparedQuery prepare(UUID knowledgeBaseId, String question, String traceId) {
        // 先按当前 ThreadLocal 租户验证 kb，异步线程不再读取 TenantContext。
        knowledgeBaseService.getByIdAndCurrentOrg(knowledgeBaseId);
        UUID organizationId = requireOrganizationId();
        UUID memberId = requireMemberId();
        long retrievalStartedAt = System.nanoTime();
        RetrievalResult result = retriever.retrieveWithDecision(organizationId, knowledgeBaseId, question,
                RetrievalOptions.defaults());
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
        return new PreparedQuery(question, result.chunks(), CitationBuilder.build(result.chunks(), documentNames), null,
                audit);
    }

    public GenerationMetrics stream(PreparedQuery query, Consumer<QueryEvent> eventConsumer) {
        if (query.refusalReason() != null) {
            eventConsumer.accept(QueryEvent.refusal(query.refusalReason()));
            return GenerationMetrics.none();
        }
        query.citations().forEach(citation -> eventConsumer.accept(QueryEvent.source(citation)));
        return answerGenerator.streamWithMetrics(query.question(), query.contexts(), eventConsumer);
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

    public record PreparedQuery(String question, List<RetrievedChunk> contexts, List<Citation> citations,
                                String refusalReason, QueryAuditSnapshot audit) {
        public PreparedQuery {
            contexts = contexts == null ? List.of() : List.copyOf(contexts);
            citations = citations == null ? List.of() : List.copyOf(citations);
        }

        static PreparedQuery refused(String question, String reason, QueryAuditSnapshot audit) {
            return new PreparedQuery(question, List.of(), List.of(), reason, audit);
        }
    }
}
