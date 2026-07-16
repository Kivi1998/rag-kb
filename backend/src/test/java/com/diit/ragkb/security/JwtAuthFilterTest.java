package com.diit.ragkb.security;

import org.junit.jupiter.api.Test;
import org.springframework.web.filter.OncePerRequestFilter;

import java.lang.reflect.Method;

import static org.junit.jupiter.api.Assertions.assertFalse;

/**
 * 回归测试：{@code shouldNotFilterAsyncDispatch()} 必须返回 false。
 *
 * <p>背景：本项目是无状态 JWT 认证，没有 session 态的 {@code SecurityContextRepository}
 * 在每次 dispatch 时重新装载 Authentication。{@link OncePerRequestFilter} 默认在 Servlet
 * 异步补发（ASYNC dispatch）时跳过本过滤器，这个默认值只对 session 态认证安全；对无状态
 * JWT 认证而言，跳过会导致 SseEmitter 流式接口（如 /query）在异步收尾阶段的重新分发里没有
 * Authentication，被 AuthorizationFilter 拒绝——SSE 响应最终关闭失败，浏览器收不到流结束
 * 信号，界面卡在"生成中"（2026-07-16 真实踩过，见 JwtAuthFilter 类注释）。若未来有人"清理"
 * 这个 override 觉得多余，这个测试会先失败。</p>
 */
class JwtAuthFilterTest {

    @Test
    void doesNotSkipAsyncDispatch() throws Exception {
        JwtAuthFilter filter = new JwtAuthFilter(null, null, null, null, null);
        Method method = OncePerRequestFilter.class.getDeclaredMethod("shouldNotFilterAsyncDispatch");
        method.setAccessible(true);

        boolean shouldSkip = (boolean) method.invoke(filter);

        assertFalse(shouldSkip, "无状态 JWT 认证下，本过滤器必须在 ASYNC dispatch 时也重新校验，"
                + "否则 SSE 流式接口的异步收尾会被 AuthorizationFilter 拒绝");
    }
}
