package com.diit.ragkb.ragcore.ingestion;

/** 旧 Worker 的租约已被接管，必须立即停止对任务状态的任何写入。 */
public class StaleIngestionLeaseException extends IllegalStateException {

    public StaleIngestionLeaseException(String message) {
        super(message);
    }
}
