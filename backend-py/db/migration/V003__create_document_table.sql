-- V003: 文档表
-- 文档隶属于知识库,冗余 org_id 以便 Hibernate @Filter 直接过滤

CREATE TABLE document (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kb_id           UUID         NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
    org_id          UUID         NOT NULL REFERENCES organization(id),
    name            VARCHAR(500) NOT NULL,
    content_type    VARCHAR(200),
    size_bytes      BIGINT       NOT NULL DEFAULT 0,
    ragflow_doc_id  VARCHAR(200),
    status          VARCHAR(30)  NOT NULL DEFAULT 'UPLOADING',  -- UPLOADING / PARSING / READY / FAILED
    error_message   TEXT,
    created_by      UUID         REFERENCES member(id),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_document_org_id ON document(org_id);
CREATE INDEX idx_document_kb_id  ON document(kb_id);
