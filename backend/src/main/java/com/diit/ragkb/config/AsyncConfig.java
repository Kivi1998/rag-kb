package com.diit.ragkb.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.util.concurrent.Executor;

/**
 * 异步配置
 *
 * 专用 queryExecutor 线程池:隔离流式长连接与普通请求
 * - core=10, max=50, queue=200
 * - 线程名前缀:query-
 */
@Configuration
@EnableAsync
public class AsyncConfig {

    @Bean("queryExecutor")
    public Executor queryExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(10);
        executor.setMaxPoolSize(50);
        executor.setQueueCapacity(200);
        executor.setThreadNamePrefix("query-");
        executor.initialize();
        return executor;
    }
}
