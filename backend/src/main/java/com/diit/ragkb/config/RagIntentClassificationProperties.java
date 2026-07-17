package com.diit.ragkb.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** LLM Prompt 查询意图分类开关；复用 {@code rag.model.generation} 端点，本身不需要独立端点配置。 */
@ConfigurationProperties(prefix = "rag.intent-classification")
public class RagIntentClassificationProperties {

    private boolean enabled;

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }
}
