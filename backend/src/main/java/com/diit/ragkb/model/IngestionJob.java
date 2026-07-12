package com.diit.ragkb.model;

import com.diit.ragkb.ragcore.model.IngestionStatus;
import jakarta.persistence.*;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.Filter;

import java.time.Instant;
import java.util.UUID;

/** 文档异步摄取任务。 */
@Data
@NoArgsConstructor
@Entity
@Table(name = "ingestion_job")
@Filter(name = "tenantFilter", condition = "org_id = :orgId")
public class IngestionJob {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "document_id", nullable = false)
    private KnowledgeDocument document;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "org_id", nullable = false)
    private Organization org;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "kb_id", nullable = false)
    private KnowledgeBase knowledgeBase;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 30)
    private IngestionStatus status = IngestionStatus.QUEUED;

    @Column(nullable = false)
    private int attempt;

    @Column(name = "max_attempts", nullable = false)
    private int maxAttempts = 3;

    @Column(name = "error_message")
    private String errorMessage;

    @Column(name = "started_at")
    private Instant startedAt;

    @Column(name = "finished_at")
    private Instant finishedAt;

    /** 当前处理实例及其租约；用于多实例竞争与故障接管。 */
    @Column(name = "lease_owner", length = 200)
    private String leaseOwner;

    @Column(name = "lease_expires_at")
    private Instant leaseExpiresAt;

    @Column(name = "last_heartbeat_at")
    private Instant lastHeartbeatAt;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    @PrePersist
    void prePersist() {
        Instant now = Instant.now();
        createdAt = now;
        updatedAt = now;
    }

    @PreUpdate
    void preUpdate() {
        updatedAt = Instant.now();
    }
}
