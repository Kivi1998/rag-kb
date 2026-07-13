-- V011: 大文件 complete 使用短事务领取校验权，实际对象读取不占用数据库行锁。

ALTER TABLE document_upload_session
    ADD COLUMN verification_token UUID,
    ADD COLUMN verification_started_at TIMESTAMPTZ,
    ADD CONSTRAINT chk_upload_verification_lease
        CHECK ((status = 'VERIFYING' AND verification_token IS NOT NULL AND verification_started_at IS NOT NULL)
            OR (status <> 'VERIFYING' AND verification_token IS NULL AND verification_started_at IS NULL));

CREATE INDEX idx_upload_session_verification_recovery
    ON document_upload_session (verification_started_at)
    WHERE status = 'VERIFYING';

COMMENT ON COLUMN document_upload_session.verification_token IS '校验 fencing token，防止超时校验者提交';
COMMENT ON COLUMN document_upload_session.verification_started_at IS '服务端开始读取对象并计算 SHA-256 的时间';
