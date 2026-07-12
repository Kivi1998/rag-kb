package com.diit.ragkb.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** RAG chunk 索引的 Elasticsearch 连接与向量字段配置。 */
@ConfigurationProperties(prefix = "rag.elasticsearch")
public class RagElasticsearchProperties {

    private boolean enabled;
    private String endpoint;
    private String apiKey;
    private String indexName = "rag_chunks_v1";
    private int vectorDimensions;
    private int connectTimeoutMs = 3_000;
    private int socketTimeoutMs = 30_000;

    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean enabled) { this.enabled = enabled; }
    public String getEndpoint() { return endpoint; }
    public void setEndpoint(String endpoint) { this.endpoint = endpoint; }
    public String getApiKey() { return apiKey; }
    public void setApiKey(String apiKey) { this.apiKey = apiKey; }
    public String getIndexName() { return indexName; }
    public void setIndexName(String indexName) { this.indexName = indexName; }
    public int getVectorDimensions() { return vectorDimensions; }
    public void setVectorDimensions(int vectorDimensions) { this.vectorDimensions = vectorDimensions; }
    public int getConnectTimeoutMs() { return connectTimeoutMs; }
    public void setConnectTimeoutMs(int connectTimeoutMs) { this.connectTimeoutMs = connectTimeoutMs; }
    public int getSocketTimeoutMs() { return socketTimeoutMs; }
    public void setSocketTimeoutMs(int socketTimeoutMs) { this.socketTimeoutMs = socketTimeoutMs; }
}
