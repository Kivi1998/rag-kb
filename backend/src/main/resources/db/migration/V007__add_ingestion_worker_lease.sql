-- V007: 多实例摄取 Worker 租约。租约过期的任务可被安全接管，避免进程异常后永久卡在处理中。

ALTER TABLE ingestion_job
    ADD COLUMN lease_owner VARCHAR(200),
    ADD COLUMN lease_expires_at TIMESTAMPTZ,
    ADD COLUMN last_heartbeat_at TIMESTAMPTZ;

CREATE INDEX idx_ingestion_job_lease_recovery
    ON ingestion_job (lease_expires_at)
    WHERE status IN ('PARSING', 'CHUNKING', 'EMBEDDING', 'INDEXING');

COMMENT ON COLUMN ingestion_job.lease_owner IS '当前处理任务的 Worker 实例标识';
COMMENT ON COLUMN ingestion_job.lease_expires_at IS 'Worker 租约到期时间；过期任务可恢复入队';
