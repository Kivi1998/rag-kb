package com.diit.ragkb.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;

/**
 * Redis 操作封装
 * 用于 token 黑名单等场景
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class RedisService {

    private final StringRedisTemplate redisTemplate;

    /**
     * 设置 key-value 并指定 TTL(秒)
     */
    public void setWithTTL(String key, String value, long ttlSeconds) {
        redisTemplate.opsForValue().set(key, value, Duration.ofSeconds(ttlSeconds));
    }

    /**
     * 检查 key 是否存在
     */
    public boolean exists(String key) {
        return Boolean.TRUE.equals(redisTemplate.hasKey(key));
    }

    /**
     * 检查 Redis 是否可达
     */
    public boolean isAvailable() {
        try {
            redisTemplate.hasKey("__health_check__");
            return true;
        } catch (Exception e) {
            log.warn("Redis 不可达: {}", e.getMessage());
            return false;
        }
    }
}
