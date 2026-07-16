package com.diit.ragkb.model;

import jakarta.persistence.*;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.Filter;

import java.time.Instant;
import java.util.UUID;

/**
 * 多轮对话会话生命周期元数据。会话内容(消息/画像)本身存 MongoDB，
 * 这里只存 Hibernate {@code tenantFilter} 需要的归属与状态机字段。
 */
@Data
@NoArgsConstructor
@Entity
@Table(name = "chat_session")
@Filter(name = "tenantFilter", condition = "org_id = :orgId")
public class ChatSession {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "org_id", nullable = false)
    private Organization org;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "kb_id", nullable = false)
    private KnowledgeBase kb;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "member_id", nullable = false)
    private Member member;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private ChatSessionStatus status = ChatSessionStatus.ACTIVE;

    @Column(name = "last_active_at", nullable = false)
    private Instant lastActiveAt;

    /** 首条用户消息前 30 字，写入时算好，只在为空时写一次；供历史会话列表展示，非首轮不覆盖。 */
    @Column(length = 64)
    private String title;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    @PrePersist
    void prePersist() {
        Instant now = Instant.now();
        this.createdAt = now;
        this.updatedAt = now;
        if (this.lastActiveAt == null) {
            this.lastActiveAt = now;
        }
    }

    @PreUpdate
    void preUpdate() {
        this.updatedAt = Instant.now();
    }
}
