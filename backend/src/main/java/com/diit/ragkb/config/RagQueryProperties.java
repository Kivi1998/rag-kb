package com.diit.ragkb.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** SSE 问答连接与专用执行器配置。 */
@ConfigurationProperties(prefix = "rag.query")
public class RagQueryProperties {

    private long streamTimeoutMs = 120_000;
    private int workerThreads = 8;

    public long getStreamTimeoutMs() {
        return streamTimeoutMs;
    }

    public void setStreamTimeoutMs(long streamTimeoutMs) {
        this.streamTimeoutMs = streamTimeoutMs;
    }

    public int getWorkerThreads() {
        return workerThreads;
    }

    public void setWorkerThreads(int workerThreads) {
        this.workerThreads = workerThreads;
    }
}
