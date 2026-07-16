package com.diit.ragkb.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** 本机部署的 NLI（自然语言推理）网关配置；不是 OpenAI 兼容端点，无需 apiKey/model 字段。 */
@ConfigurationProperties(prefix = "rag.nli")
public class RagNliProperties {

    private boolean enabled;
    private String endpoint;
    private long timeoutMs = 15_000;

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public String getEndpoint() {
        return endpoint;
    }

    public void setEndpoint(String endpoint) {
        this.endpoint = endpoint;
    }

    public long getTimeoutMs() {
        return timeoutMs;
    }

    public void setTimeoutMs(long timeoutMs) {
        this.timeoutMs = timeoutMs;
    }
}
