-- V009: MinIO/S3 预签名直传会话。完成回调前不创建 ingestion_job，避免半上传对象被消费。

CREATE TABLE document_upload_session (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organization(id),
    kb_id UUID NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
    created_by UUID NOT NULL REFERENCES member(id),
    file_name VARCHAR(500) NOT NULL,
    content_type VARCHAR(200) NOT NULL,
    expected_size_bytes BIGINT NOT NULL,
    object_storage_path VARCHAR(1000) NOT NULL,
    idempotency_key VARCHAR(200) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    document_id UUID REFERENCES document(id) ON DELETE SET NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_upload_session_size CHECK (expected_size_bytes > 0),
    CONSTRAINT uq_upload_session_idempotency UNIQUE (org_id, kb_id, idempotency_key)
);

CREATE INDEX idx_upload_session_expiry
    ON document_upload_session (expires_at)
    WHERE status = 'PENDING';
