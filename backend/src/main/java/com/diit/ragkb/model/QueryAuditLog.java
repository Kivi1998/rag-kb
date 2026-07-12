package com.diit.ragkb.model;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.Instant;
import java.util.UUID;

/** 不保存问题、回答、Prompt 或正文的 RAG 查询审计记录。 */
@Data
@NoArgsConstructor
@Entity
@Table(name = "rag_query_audit")
public class QueryAuditLog {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @Column(name = "trace_id", nullable = false, unique = true, length = 64)
    private String traceId;

    @Column(name = "org_id", nullable = false)
    private UUID organizationId;

    @Column(name = "kb_id", nullable = false)
    private UUID knowledgeBaseId;

    @Column(name = "member_id", nullable = false)
    private UUID memberId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private QueryAuditStatus status;

    @Column(name = "retrieval_latency_ms", nullable = false)
    private long retrievalLatencyMs;

    @Column(name = "generation_latency_ms", nullable = false)
    private long generationLatencyMs;

    @Column(name = "total_latency_ms", nullable = false)
    private long totalLatencyMs;

    @Column(name = "chunk_ids_json", columnDefinition = "TEXT", nullable = false)
    private String chunkIdsJson;

    @Column(name = "document_ids_json", columnDefinition = "TEXT", nullable = false)
    private String documentIdsJson;

    @Column(name = "final_scores_json", columnDefinition = "TEXT", nullable = false)
    private String finalScoresJson;

    @Column(name = "embedding_fallback", nullable = false)
    private boolean embeddingFallback;

    @Column(name = "rerank_fallback", nullable = false)
    private boolean rerankFallback;

    @Column(name = "refusal_reason", length = 300)
    private String refusalReason;

    @Column(name = "generation_model", length = 300)
    private String generationModel;

    @Column(name = "prompt_tokens")
    private Integer promptTokens;

    @Column(name = "completion_tokens")
    private Integer completionTokens;

    @Column(name = "output_characters", nullable = false)
    private long outputCharacters;

    @Column(name = "error_code", length = 100)
    private String errorCode;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @jakarta.persistence.PrePersist
    void prePersist() {
        if (createdAt == null) createdAt = Instant.now();
    }
}
