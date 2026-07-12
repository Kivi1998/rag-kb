package com.diit.ragkb.model;

import com.diit.ragkb.ragcore.model.IngestionStatus;
import jakarta.persistence.*;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.Filter;

import java.time.Instant;
import java.util.UUID;

/** 知识库中的原始技术文档及其对象存储定位。 */
@Data
@NoArgsConstructor
@Entity
@Table(name = "document")
@Filter(name = "tenantFilter", condition = "org_id = :orgId")
public class KnowledgeDocument {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "kb_id", nullable = false)
    private KnowledgeBase knowledgeBase;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "org_id", nullable = false)
    private Organization org;

    @Column(nullable = false, length = 500)
    private String name;

    @Column(name = "content_type", length = 200)
    private String contentType;

    @Column(name = "size_bytes", nullable = false)
    private long sizeBytes;

    @Column(name = "object_storage_path", length = 1000)
    private String objectStoragePath;

    /** 原始文件的 SHA-256，用于审计、内容去重与版本追溯。 */
    @Column(name = "content_sha256", length = 64)
    private String contentSha256;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 30)
    private IngestionStatus status = IngestionStatus.QUEUED;

    @Column(name = "retry_count", nullable = false)
    private int retryCount;

    @Column(name = "last_error")
    private String lastError;

    @Column(name = "last_error_at")
    private Instant lastErrorAt;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "created_by")
    private Member createdBy;

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
