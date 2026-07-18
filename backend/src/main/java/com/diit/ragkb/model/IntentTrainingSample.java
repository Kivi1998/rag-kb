package com.diit.ragkb.model;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.Filter;

import java.time.Instant;
import java.util.UUID;

/**
 * 意图分类训练数据留存：存「问题原文 + 预测意图标签」，供未来训练 BERT 分类器使用。
 *
 * <p>与 {@link QueryAuditLog} 不同——本表存问题原文，明文不脱敏，默认开启
 * （{@code rag.intent-training-data.enabled=true}），不做自动清理，均为 2026-07-17
 * brainstorming 阶段用户明确决定。</p>
 */
@Data
@NoArgsConstructor
@Entity
@Table(name = "intent_training_sample")
@Filter(name = "tenantFilter", condition = "org_id = :orgId")
public class IntentTrainingSample {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @Column(name = "org_id", nullable = false)
    private UUID orgId;

    @Column(name = "kb_id", nullable = false)
    private UUID kbId;

    @Column(name = "member_id", nullable = false)
    private UUID memberId;

    @Column(nullable = false, columnDefinition = "TEXT")
    private String question;

    @Column(name = "predicted_intent", nullable = false, length = 32)
    private String predictedIntent;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @jakarta.persistence.PrePersist
    void prePersist() {
        if (createdAt == null) createdAt = Instant.now();
    }
}
