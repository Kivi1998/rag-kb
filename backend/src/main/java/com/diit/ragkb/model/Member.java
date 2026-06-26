package com.diit.ragkb.model;

import jakarta.persistence.*;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.Filter;

import java.time.Instant;
import java.util.UUID;

/**
 * 成员:subject(认证主体)在某组织内的身份
 * 唯一约束 (subject_id, org_id) — 一个 subject 在一个组织只能有一条记录
 */
@Data
@NoArgsConstructor
@Entity
@Table(name = "member",
       uniqueConstraints = @UniqueConstraint(columnNames = {"subject_id", "org_id"}))
@Filter(name = "tenantFilter", condition = "org_id = :orgId")
public class Member {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    /** 认证主体标识(对齐未来 OIDC 的 sub) */
    @Column(name = "subject_id", nullable = false, length = 200)
    private String subjectId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "org_id", nullable = false)
    private Organization org;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private MemberRole role = MemberRole.MEMBER;

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
