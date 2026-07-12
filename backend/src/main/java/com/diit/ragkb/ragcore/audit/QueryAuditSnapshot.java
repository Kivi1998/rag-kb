package com.diit.ragkb.ragcore.audit;

import com.diit.ragkb.ragcore.model.RetrievedChunk;
import com.diit.ragkb.ragcore.retrieval.RetrievalDiagnostics;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.UUID;

/** 单次查询的安全审计快照：只含标识、分数与状态，不含问题或文档正文。 */
public record QueryAuditSnapshot(
        String traceId,
        UUID organizationId,
        UUID knowledgeBaseId,
        UUID memberId,
        long retrievalLatencyMs,
        List<String> chunkIds,
        List<UUID> documentIds,
        List<Double> finalScores,
        RetrievalDiagnostics diagnostics,
        boolean refused,
        String refusalReason
) {
    public QueryAuditSnapshot {
        if (traceId == null || traceId.isBlank() || organizationId == null || knowledgeBaseId == null || memberId == null) {
            throw new IllegalArgumentException("审计快照缺少 traceId、组织、知识库或成员");
        }
        if (retrievalLatencyMs < 0) throw new IllegalArgumentException("检索耗时不能为负数");
        chunkIds = chunkIds == null ? List.of() : List.copyOf(chunkIds);
        documentIds = documentIds == null ? List.of() : List.copyOf(documentIds);
        finalScores = finalScores == null ? List.of() : List.copyOf(finalScores);
        diagnostics = diagnostics == null ? RetrievalDiagnostics.empty() : diagnostics;
    }

    public static QueryAuditSnapshot from(String traceId, UUID organizationId, UUID knowledgeBaseId, UUID memberId,
                                          long retrievalLatencyMs, List<RetrievedChunk> chunks,
                                          RetrievalDiagnostics diagnostics, boolean refused, String refusalReason) {
        List<RetrievedChunk> safeChunks = chunks == null ? List.of() : chunks;
        return new QueryAuditSnapshot(traceId, organizationId, knowledgeBaseId, memberId, retrievalLatencyMs,
                safeChunks.stream().map(item -> item.chunk().id()).toList(),
                List.copyOf(new LinkedHashSet<>(safeChunks.stream().map(item -> item.chunk().documentId()).toList())),
                safeChunks.stream().map(RetrievedChunk::finalScore).filter(java.util.Objects::nonNull).toList(),
                diagnostics, refused, refusalReason);
    }

    public static QueryAuditSnapshot beforeRetrieval(String traceId, UUID organizationId, UUID knowledgeBaseId,
                                                     UUID memberId) {
        return from(traceId, organizationId, knowledgeBaseId, memberId, 0, List.of(), RetrievalDiagnostics.empty(),
                false, null);
    }
}
