-- V005: 自研 RAG 文档摄取任务与对象存储定位
-- 不修改历史 RAGFlow 字段；新链路只使用 object_storage_path 与 ingestion_job。

ALTER TABLE document
    ADD COLUMN object_storage_path VARCHAR(1000),
    ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN last_error TEXT,
    ADD COLUMN last_error_at TIMESTAMPTZ;

ALTER TABLE document
    ALTER COLUMN status SET DEFAULT 'QUEUED';

-- 首期旧表以 UPLOADING 作为默认状态；新状态机统一从 QUEUED 开始，避免 ORM 枚举无法读取旧值。
UPDATE document SET status = 'QUEUED' WHERE status = 'UPLOADING';

CREATE TABLE ingestion_job (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    org_id UUID NOT NULL REFERENCES organization(id),
    kb_id UUID NOT NULL REFERENCES knowledge_base(id),
    status VARCHAR(30) NOT NULL DEFAULT 'QUEUED',
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_ingestion_job_attempts CHECK (attempt >= 0 AND max_attempts > 0)
);

CREATE INDEX idx_ingestion_job_document_id ON ingestion_job(document_id);
CREATE INDEX idx_ingestion_job_org_kb_status ON ingestion_job(org_id, kb_id, status);
CREATE INDEX idx_ingestion_job_queued ON ingestion_job(created_at) WHERE status = 'QUEUED';

-- 同一文档同一时间只能有一个活跃摄取流程；FAILED 必须显式重试后迁回 QUEUED。
CREATE UNIQUE INDEX uq_ingestion_job_active_document
    ON ingestion_job(document_id)
    WHERE status IN ('QUEUED', 'PARSING', 'CHUNKING', 'EMBEDDING', 'INDEXING');

COMMENT ON TABLE ingestion_job IS '自研 RAG 文档异步摄取任务';
COMMENT ON COLUMN document.object_storage_path IS 'MinIO/S3 对象键，格式 org/{orgId}/kb/{kbId}/documents/{documentId}.{ext}';
