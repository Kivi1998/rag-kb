-- V012: 多轮对话会话生命周期元数据
-- 会话内容本身(消息/画像)存 MongoDB,这里只存 Hibernate tenantFilter 需要的归属与状态机字段

CREATE TABLE chat_session (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID         NOT NULL REFERENCES organization(id),
    kb_id           UUID         NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
    member_id       UUID         NOT NULL REFERENCES member(id),
    status          VARCHAR(20)  NOT NULL DEFAULT 'ACTIVE',  -- ACTIVE / IDLE / ARCHIVED
    last_active_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_chat_session_org_id ON chat_session(org_id);
CREATE INDEX idx_chat_session_kb_id ON chat_session(kb_id);
CREATE INDEX idx_chat_session_member_id ON chat_session(member_id);
CREATE INDEX idx_chat_session_last_active_at ON chat_session(last_active_at);

COMMENT ON COLUMN chat_session.status IS 'ACTIVE=30分钟内有新消息;IDLE=超过30分钟未超2小时;ARCHIVED=超过2小时;有新消息随时续期回ACTIVE';
