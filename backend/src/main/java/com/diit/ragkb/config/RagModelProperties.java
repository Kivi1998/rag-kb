package com.diit.ragkb.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** RAG 外部模型服务配置；凭证仅允许来自环境变量或 secret 文件。 */
@ConfigurationProperties(prefix = "rag.model")
public class RagModelProperties {

    private final Embedding embedding = new Embedding();
    private final Rerank rerank = new Rerank();
    private final Generation generation = new Generation();

    public Embedding getEmbedding() {
        return embedding;
    }

    public Rerank getRerank() {
        return rerank;
    }

    public Generation getGeneration() {
        return generation;
    }

    public static class Embedding extends Endpoint {
        private int batchSize = 32;

        public int getBatchSize() {
            return batchSize;
        }

        public void setBatchSize(int batchSize) {
            this.batchSize = batchSize;
        }
    }

    public static class Rerank extends Endpoint {
    }

    /** OpenAI Chat Completions 兼容的流式生成端点。 */
    public static class Generation extends Endpoint {
        private boolean includeUsage = true;

        public boolean isIncludeUsage() {
            return includeUsage;
        }

        public void setIncludeUsage(boolean includeUsage) {
            this.includeUsage = includeUsage;
        }
    }

    public abstract static class Endpoint {
        private boolean enabled;
        private String endpoint;
        private String apiKey;
        private String model;
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

        public String getApiKey() {
            return apiKey;
        }

        public void setApiKey(String apiKey) {
            this.apiKey = apiKey;
        }

        public String getModel() {
            return model;
        }

        public void setModel(String model) {
            this.model = model;
        }

        public long getTimeoutMs() {
            return timeoutMs;
        }

        public void setTimeoutMs(long timeoutMs) {
            this.timeoutMs = timeoutMs;
        }
    }
}
