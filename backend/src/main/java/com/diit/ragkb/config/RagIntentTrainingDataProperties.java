package com.diit.ragkb.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 意图分类训练数据留存开关。默认开启（与 {@code rag.nli.enabled}/
 * {@code rag.intent-classification.enabled} 等默认关闭的既有保守惯例不同），是
 * 2026-07-17 brainstorming 阶段用户明确选择——开启后会把问题原文明文写入
 * {@code intent_training_sample} 表，不脱敏、不自动清理。
 */
@ConfigurationProperties(prefix = "rag.intent-training-data")
public class RagIntentTrainingDataProperties {

    private boolean enabled = true;

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }
}
