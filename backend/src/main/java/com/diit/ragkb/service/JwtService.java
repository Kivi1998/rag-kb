package com.diit.ragkb.service;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.UUID;

/**
 * JWT 签发与验证服务
 *
 * payload:
 * - sub: userId
 * - jti: 唯一标识(用于 Redis 黑名单)
 * - tv:  tokenVersion(用于管理员重置后旧 token 失效)
 * - exp: 过期时间
 */
@Service
public class JwtService {

    private static final int MINIMUM_HS256_SECRET_BYTES = 32;

    private final SecretKey signingKey;
    private final long expirationSeconds;

    public JwtService(@Value("${spring.security.jwt.secret}") String secret,
                      @Value("${spring.security.jwt.expiration-seconds:86400}") long expirationSeconds) {
        if (secret == null || secret.isBlank()) {
            throw new IllegalStateException("JWT_SECRET 未配置，服务拒绝启动");
        }
        byte[] secretBytes = secret.getBytes(StandardCharsets.UTF_8);
        if (secretBytes.length < MINIMUM_HS256_SECRET_BYTES) {
            throw new IllegalStateException("JWT_SECRET 至少需要 32 个字节");
        }
        if (expirationSeconds <= 0) {
            throw new IllegalStateException("JWT_EXPIRATION_SECONDS 必须大于 0");
        }
        this.signingKey = Keys.hmacShaKeyFor(secretBytes);
        this.expirationSeconds = expirationSeconds;
    }

    /**
     * 签发 JWT
     */
    public String generateToken(UUID userId, int tokenVersion) {
        Date now = new Date();
        Date exp = new Date(now.getTime() + expirationSeconds * 1000);

        return Jwts.builder()
                .subject(userId.toString())
                .id(UUID.randomUUID().toString())  // jti
                .claim("tv", tokenVersion)
                .issuedAt(now)
                .expiration(exp)
                .signWith(signingKey)
                .compact();
    }

    /**
     * 解析并验证 JWT(签名+有效期)
     *
     * @return Claims; 解析失败返回 null
     */
    public Claims parseToken(String token) {
        try {
            return Jwts.parser()
                    .verifyWith(signingKey)
                    .build()
                    .parseSignedClaims(token)
                    .getPayload();
        } catch (JwtException e) {
            return null;
        }
    }

    /** 获取 token 剩余有效期(秒) */
    public long getRemainingSeconds(Claims claims) {
        Date exp = claims.getExpiration();
        return Math.max(0, (exp.getTime() - System.currentTimeMillis()) / 1000);
    }

    /** 获取配置的总有效期(秒) */
    public long getExpirationSeconds() {
        return expirationSeconds;
    }
}
