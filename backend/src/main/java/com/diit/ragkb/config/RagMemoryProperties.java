package com.diit.ragkb.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** 多轮对话与记忆管理子系统配置：Redis 逻辑 DB、MongoDB 连接、ES 记忆索引与各类阈值。 */
@ConfigurationProperties(prefix = "rag.memory")
public class RagMemoryProperties {

    private boolean enabled;
    private int redisDatabase = 1;
    private String mongoUri;
    private String memoryIndexName = "rag_memory_v1";
    private int tokenBudget = 1000;
    private int decayHalfLifeDays = 30;
    private int profileTopK = 5;
    private int sessionActiveMinutes = 30;
    private int sessionIdleHours = 2;

    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean enabled) { this.enabled = enabled; }
    public int getRedisDatabase() { return redisDatabase; }
    public void setRedisDatabase(int redisDatabase) { this.redisDatabase = redisDatabase; }
    public String getMongoUri() { return mongoUri; }
    public void setMongoUri(String mongoUri) { this.mongoUri = mongoUri; }
    public String getMemoryIndexName() { return memoryIndexName; }
    public void setMemoryIndexName(String memoryIndexName) { this.memoryIndexName = memoryIndexName; }
    public int getTokenBudget() { return tokenBudget; }
    public void setTokenBudget(int tokenBudget) { this.tokenBudget = tokenBudget; }
    public int getDecayHalfLifeDays() { return decayHalfLifeDays; }
    public void setDecayHalfLifeDays(int decayHalfLifeDays) { this.decayHalfLifeDays = decayHalfLifeDays; }
    public int getProfileTopK() { return profileTopK; }
    public void setProfileTopK(int profileTopK) { this.profileTopK = profileTopK; }
    public int getSessionActiveMinutes() { return sessionActiveMinutes; }
    public void setSessionActiveMinutes(int sessionActiveMinutes) { this.sessionActiveMinutes = sessionActiveMinutes; }
    public int getSessionIdleHours() { return sessionIdleHours; }
    public void setSessionIdleHours(int sessionIdleHours) { this.sessionIdleHours = sessionIdleHours; }
}
