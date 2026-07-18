package com.diit.ragkb.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** 知识库向量检索切流、影子读与回退配置。 */
@ConfigurationProperties(prefix = "rag.vector")
public class VectorProviderProperties {

    private VectorProvider provider = VectorProvider.ELASTICSEARCH;
    private boolean fallbackToElasticsearch = true;
    private int shadowTimeoutMs = 1_500;
    private double shadowSampleRate = 1.0;

    public VectorProvider getProvider() { return provider; }
    public void setProvider(VectorProvider provider) { this.provider = provider; }
    public boolean isFallbackToElasticsearch() { return fallbackToElasticsearch; }
    public void setFallbackToElasticsearch(boolean fallbackToElasticsearch) {
        this.fallbackToElasticsearch = fallbackToElasticsearch;
    }
    public int getShadowTimeoutMs() { return shadowTimeoutMs; }
    public void setShadowTimeoutMs(int shadowTimeoutMs) { this.shadowTimeoutMs = shadowTimeoutMs; }
    public double getShadowSampleRate() { return shadowSampleRate; }
    public void setShadowSampleRate(double shadowSampleRate) { this.shadowSampleRate = shadowSampleRate; }

    void validate() {
        if (provider == null) {
            throw new IllegalStateException("向量 Provider 不能为空");
        }
        if (shadowTimeoutMs <= 0) {
            throw new IllegalStateException("影子查询超时必须为正数");
        }
        if (shadowSampleRate < 0 || shadowSampleRate > 1) {
            throw new IllegalStateException("影子查询采样率必须在 0 到 1 之间");
        }
    }
}
