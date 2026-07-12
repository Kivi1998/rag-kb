package com.diit.ragkb.service;

import com.diit.ragkb.model.QueryAuditLog;
import com.diit.ragkb.model.QueryAuditStatus;
import com.diit.ragkb.ragcore.audit.QueryAuditSnapshot;
import com.diit.ragkb.ragcore.generation.GenerationMetrics;
import com.diit.ragkb.repository.QueryAuditLogRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/** 将无正文审计摘要持久化，同时输出同 traceId 的结构化日志。 */
@Slf4j
@Service
@RequiredArgsConstructor
public class QueryAuditService {

    private final QueryAuditLogRepository repository;
    private final ObjectMapper objectMapper;

    /** 审计故障不得反向影响已开始的 SSE 响应。 */
    public void recordSafely(QueryAuditSnapshot snapshot, QueryAuditStatus status, GenerationMetrics metrics,
                             long generationLatencyMs, long totalLatencyMs, String errorCode) {
        try {
            record(snapshot, status, metrics, generationLatencyMs, totalLatencyMs, errorCode);
        } catch (RuntimeException ex) {
            log.error("RAG 查询审计落库失败 traceId={} status={} errorType={}", snapshot.traceId(), status,
                    ex.getClass().getSimpleName());
        }
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void record(QueryAuditSnapshot snapshot, QueryAuditStatus status, GenerationMetrics metrics,
                       long generationLatencyMs, long totalLatencyMs, String errorCode) {
        GenerationMetrics safeMetrics = metrics == null ? GenerationMetrics.none() : metrics;
        QueryAuditLog entity = new QueryAuditLog();
        entity.setTraceId(snapshot.traceId());
        entity.setOrganizationId(snapshot.organizationId());
        entity.setKnowledgeBaseId(snapshot.knowledgeBaseId());
        entity.setMemberId(snapshot.memberId());
        entity.setStatus(status);
        entity.setRetrievalLatencyMs(snapshot.retrievalLatencyMs());
        entity.setGenerationLatencyMs(Math.max(0, generationLatencyMs));
        entity.setTotalLatencyMs(Math.max(0, totalLatencyMs));
        entity.setChunkIdsJson(writeJson(snapshot.chunkIds()));
        entity.setDocumentIdsJson(writeJson(snapshot.documentIds()));
        entity.setFinalScoresJson(writeJson(snapshot.finalScores()));
        entity.setEmbeddingFallback(snapshot.diagnostics().embeddingFallback());
        entity.setRerankFallback(snapshot.diagnostics().rerankFallback());
        entity.setRefusalReason(snapshot.refusalReason());
        entity.setGenerationModel(safeMetrics.model());
        entity.setPromptTokens(safeMetrics.promptTokens());
        entity.setCompletionTokens(safeMetrics.completionTokens());
        entity.setOutputCharacters(safeMetrics.outputCharacters());
        entity.setErrorCode(errorCode);
        repository.save(entity);
        log.info("rag_query_audit traceId={} orgId={} kbId={} memberId={} status={} retrievalMs={} generationMs={} "
                        + "totalMs={} chunks={} documents={} embeddingFallback={} rerankFallback={} model={} "
                        + "promptTokens={} completionTokens={} outputCharacters={} errorCode={}",
                snapshot.traceId(), snapshot.organizationId(), snapshot.knowledgeBaseId(), snapshot.memberId(), status,
                snapshot.retrievalLatencyMs(), generationLatencyMs, totalLatencyMs, snapshot.chunkIds().size(),
                snapshot.documentIds().size(), snapshot.diagnostics().embeddingFallback(),
                snapshot.diagnostics().rerankFallback(), safeMetrics.model(), safeMetrics.promptTokens(),
                safeMetrics.completionTokens(), safeMetrics.outputCharacters(), errorCode);
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("序列化 RAG 审计标识失败", ex);
        }
    }
}
