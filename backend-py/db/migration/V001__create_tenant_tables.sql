-- V001: 租户基础表
-- 组织→团队→成员 + 知识库
-- 枚举字段用 VARCHAR 存储,Java 端用 @Enumerated(EnumType.STRING) 约束

-- ===== 组织 =====
CREATE TABLE organization (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          VARCHAR(200) NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ===== 团队 =====
CREATE TABLE team (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID         NOT NULL REFERENCES organization(id),
    name          VARCHAR(200) NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_team_org_id ON team(org_id);

-- ===== 成员(认证主体在某组织内的身份) =====
-- subject_id: 认证主体标识(对齐未来 OIDC 的 sub)
-- 一个 subject 可在多个组织各有一条 member 记录
CREATE TABLE member (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id    VARCHAR(200) NOT NULL,  -- 认证主体标识
    org_id        UUID         NOT NULL REFERENCES organization(id),
    role          VARCHAR(20)  NOT NULL DEFAULT 'MEMBER',  -- OWNER / ADMIN / MEMBER
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    -- 同一主体在同一组织只能有一条记录
    CONSTRAINT uk_member_subject_org UNIQUE (subject_id, org_id)
);
CREATE INDEX idx_member_org_id     ON member(org_id);
CREATE INDEX idx_member_subject_id ON member(subject_id);

-- ===== 知识库 =====
CREATE TABLE knowledge_base (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID         NOT NULL REFERENCES organization(id),
    team_id             UUID         REFERENCES team(id),  -- 可选归属团队
    name                VARCHAR(300) NOT NULL,
    ragflow_dataset_id  VARCHAR(200),                      -- RAGFlow dataset 映射
    status              VARCHAR(30)  NOT NULL DEFAULT 'ACTIVE',  -- ACTIVE / PENDING_CLEANUP
    created_by          UUID         REFERENCES member(id),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_kb_org_id  ON knowledge_base(org_id);
CREATE INDEX idx_kb_team_id ON knowledge_base(team_id);
