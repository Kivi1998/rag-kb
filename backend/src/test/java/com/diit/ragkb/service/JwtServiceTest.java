package com.diit.ragkb.service;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;

class JwtServiceTest {

    @Test
    void 应拒绝未配置或过短的签名密钥() {
        assertThrows(IllegalStateException.class, () -> new JwtService("", 3600));
        assertThrows(IllegalStateException.class, () -> new JwtService("too-short", 3600));
    }

    @Test
    void 应拒绝非正数的令牌有效期() {
        assertThrows(IllegalStateException.class,
                () -> new JwtService("test-secret-key-at-least-32-bytes-long-for-hs256", 0));
    }

    @Test
    void 合法配置应能初始化() {
        assertDoesNotThrow(() -> new JwtService("test-secret-key-at-least-32-bytes-long-for-hs256", 3600));
    }
}
