package com.diit.ragkb.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 会话内临时文档（长上下文直接塞入模式）配置。默认开启——不耦合 {@code rag.memory.enabled}，
 * 因为核心问答链路（{@code ChatSession}/{@code QueryController}）本来就不依赖可选的记忆子系统。
 * {@code maxTotalCharacters} 是重新校准 rag系统2 的 4000 字符设定得出的估算值（对齐
 * deepseek-chat 128K 上下文窗口），不是像 {@code MIN_RERANK_SCORE} 那样经过评估集校准的数字，
 * 做成配置项方便上线后按实际情况调整。
 */
@ConfigurationProperties(prefix = "rag.quick-document")
public class RagQuickDocumentProperties {

    private boolean enabled = true;
    private int redisDatabase = 2;
    private int ttlHours = 2;
    private int maxTotalCharacters = 15000;

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public int getRedisDatabase() {
        return redisDatabase;
    }

    public void setRedisDatabase(int redisDatabase) {
        this.redisDatabase = redisDatabase;
    }

    public int getTtlHours() {
        return ttlHours;
    }

    public void setTtlHours(int ttlHours) {
        this.ttlHours = ttlHours;
    }

    public int getMaxTotalCharacters() {
        return maxTotalCharacters;
    }

    public void setMaxTotalCharacters(int maxTotalCharacters) {
        this.maxTotalCharacters = maxTotalCharacters;
    }
}
