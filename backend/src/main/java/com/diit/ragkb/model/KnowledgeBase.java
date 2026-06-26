package com.diit.ragkb.model;

import jakarta.persistence.*;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.Filter;

import java.time.Instant;
import java.util.UUID;

/**
 * 知识库(归属唯一组织,可选归属团队)
 */
@Data
@NoArgsConstructor
@Entity
@Table(name = "knowledge_base")
@Filter(name = "tenantFilter", condition = "org_id = :orgId")
public class KnowledgeBase {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "org_id", nullable = false)
    private Organization org;

    /** 可选:归属团队 */
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "team_id")
    private Team team;

    @Column(nullable = false, length = 300)
    private String name;

    /** RAGFlow dataset ID 映射 */
    @Column(name = "ragflow_dataset_id", length = 200)
    private String ragflowDatasetId;

    /** RAGFlow Chat Assistant ID(懒建,首次问答时写入) */
    @Column(name = "ragflow_chat_id", length = 200)
    private String ragflowChatId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 30)
    private KbStatus status = KbStatus.ACTIVE;

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
        this.createdAt = now;
        this.updatedAt = now;
    }

    @PreUpdate
    void preUpdate() {
        this.updatedAt = Instant.now();
    }
}
