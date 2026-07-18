package com.diit.ragkb.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** Milvus 知识库 Chunk 向量投影配置；不用于会话记忆索引。 */
@ConfigurationProperties(prefix = "rag.milvus")
public class RagMilvusProperties {

    private boolean enabled;
    private String uri;
    private boolean authEnabled;
    private String token;
    private String username;
    private String password;
    private String databaseName = "default";
    private String collectionName = "rag_chunks_vector_v1";
    private int vectorDimensions = 1_024;
    private String metricType = "COSINE";
    private String indexType = "HNSW";
    private int hnswM = 16;
    private int efConstruction = 200;
    private int searchEf = 128;
    private int connectTimeoutMs = 3_000;
    private int rpcTimeoutMs = 3_000;
    private boolean tlsEnabled;

    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean enabled) { this.enabled = enabled; }
    public String getUri() { return uri; }
    public void setUri(String uri) { this.uri = uri; }
    public boolean isAuthEnabled() { return authEnabled; }
    public void setAuthEnabled(boolean authEnabled) { this.authEnabled = authEnabled; }
    public String getToken() { return token; }
    public void setToken(String token) { this.token = token; }
    public String getUsername() { return username; }
    public void setUsername(String username) { this.username = username; }
    public String getPassword() { return password; }
    public void setPassword(String password) { this.password = password; }
    public String getDatabaseName() { return databaseName; }
    public void setDatabaseName(String databaseName) { this.databaseName = databaseName; }
    public String getCollectionName() { return collectionName; }
    public void setCollectionName(String collectionName) { this.collectionName = collectionName; }
    public int getVectorDimensions() { return vectorDimensions; }
    public void setVectorDimensions(int vectorDimensions) { this.vectorDimensions = vectorDimensions; }
    public String getMetricType() { return metricType; }
    public void setMetricType(String metricType) { this.metricType = metricType; }
    public String getIndexType() { return indexType; }
    public void setIndexType(String indexType) { this.indexType = indexType; }
    public int getHnswM() { return hnswM; }
    public void setHnswM(int hnswM) { this.hnswM = hnswM; }
    public int getEfConstruction() { return efConstruction; }
    public void setEfConstruction(int efConstruction) { this.efConstruction = efConstruction; }
    public int getSearchEf() { return searchEf; }
    public void setSearchEf(int searchEf) { this.searchEf = searchEf; }
    public int getConnectTimeoutMs() { return connectTimeoutMs; }
    public void setConnectTimeoutMs(int connectTimeoutMs) { this.connectTimeoutMs = connectTimeoutMs; }
    public int getRpcTimeoutMs() { return rpcTimeoutMs; }
    public void setRpcTimeoutMs(int rpcTimeoutMs) { this.rpcTimeoutMs = rpcTimeoutMs; }
    public boolean isTlsEnabled() { return tlsEnabled; }
    public void setTlsEnabled(boolean tlsEnabled) { this.tlsEnabled = tlsEnabled; }

    void validate() {
        if (!enabled) return;
        if (isBlank(uri) || isBlank(databaseName) || isBlank(collectionName)) {
            throw new IllegalStateException("启用 Milvus 前必须配置 uri/database-name/collection-name");
        }
        if (vectorDimensions <= 0 || connectTimeoutMs <= 0 || rpcTimeoutMs <= 0) {
            throw new IllegalStateException("Milvus 向量维度和超时必须为正数");
        }
        if (!"COSINE".equalsIgnoreCase(metricType) || !"HNSW".equalsIgnoreCase(indexType)) {
            throw new IllegalStateException("当前 Milvus Collection 仅允许 HNSW + COSINE");
        }
        if (hnswM <= 0 || efConstruction <= 0 || searchEf <= 0) {
            throw new IllegalStateException("Milvus HNSW 参数必须为正数");
        }
        if (authEnabled && isBlank(token) && (isBlank(username) || isBlank(password))) {
            throw new IllegalStateException("Milvus 开启鉴权时必须配置 token 或 username/password");
        }
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }
}
