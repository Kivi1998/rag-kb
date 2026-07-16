package com.diit.ragkb.config;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;

/**
 * {@link RagMemoryProperties} 独立于 {@code rag.memory.enabled} 常驻注册。
 *
 * <p>会话生命周期管理（{@code ChatSessionService} 的 ACTIVE/IDLE/ARCHIVED 阈值）基于
 * Postgres {@code chat_session} 表，与 Redis/MongoDB/ES 记忆子系统解耦——{@code sessionId}
 * 在 QueryRequest 上始终必填，因此这份配置必须始终可用，不能像 {@link RagMemoryConfiguration}
 * 那样整体被 {@code rag.memory.enabled=false} 门控掉。</p>
 */
@Configuration
@EnableConfigurationProperties(RagMemoryProperties.class)
public class RagSessionPropertiesConfiguration {
}
