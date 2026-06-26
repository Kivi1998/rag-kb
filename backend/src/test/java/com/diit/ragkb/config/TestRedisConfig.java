package com.diit.ragkb.config;

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.serializer.StringRedisSerializer;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.verify;

/**
 * 测试用 Redis mock 配置
 * 用 ConcurrentHashMap 模拟 Redis,不依赖外部 Redis 服务
 */
@TestConfiguration
public class TestRedisConfig {

    private final Map<String, String> store = new ConcurrentHashMap<>();
    private final Map<String, Long> ttls = new ConcurrentHashMap<>();

    @Bean
    @Primary
    public StringRedisTemplate testRedisTemplate() {
        StringRedisTemplate template = mock(StringRedisTemplate.class);

        // Mock opsForValue().set(key, value, duration)
        var ops = mock(org.springframework.data.redis.core.ValueOperations.class);
        when(template.opsForValue()).thenReturn(ops);

        doAnswer(inv -> {
            String key = inv.getArgument(0);
            String value = inv.getArgument(1);
            store.put(key, value);
            return null;
        }).when(ops).set(anyString(), anyString(), any());

        // Mock hasKey()
        when(template.hasKey(anyString())).thenAnswer(inv -> store.containsKey(inv.getArgument(0)));

        return template;
    }
}
