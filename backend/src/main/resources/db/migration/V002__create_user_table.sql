-- V002: 本地账号表
-- 用于注册/登录,替代外部 JWT 占位

CREATE TABLE app_user (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               VARCHAR(300) NOT NULL UNIQUE,
    password_hash       VARCHAR(200) NOT NULL,
    display_name        VARCHAR(200) NOT NULL,
    status              VARCHAR(20)  NOT NULL DEFAULT 'ACTIVE',  -- ACTIVE / LOCKED
    failed_login_count  INT          NOT NULL DEFAULT 0,
    locked_until        TIMESTAMPTZ,
    must_change_password BOOLEAN     NOT NULL DEFAULT FALSE,
    token_version       INT          NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_user_email ON app_user(email);
