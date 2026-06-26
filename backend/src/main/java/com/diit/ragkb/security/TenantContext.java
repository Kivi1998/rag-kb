package com.diit.ragkb.security;

import java.util.UUID;

/**
 * 请求级租户上下文(基于 ThreadLocal)
 * 生命周期:过滤器入口注入 → Service 使用 → finally 无条件清理
 */
public final class TenantContext {

    private static final ThreadLocal<UUID> ORG_ID = new ThreadLocal<>();
    private static final ThreadLocal<UUID> MEMBER_ID = new ThreadLocal<>();
    private static final ThreadLocal<String> ROLE = new ThreadLocal<>();

    private TenantContext() {}

    public static void set(UUID orgId, UUID memberId, String role) {
        ORG_ID.set(orgId);
        MEMBER_ID.set(memberId);
        ROLE.set(role);
    }

    public static UUID getOrgId() {
        return ORG_ID.get();
    }

    public static UUID getMemberId() {
        return MEMBER_ID.get();
    }

    public static String getRole() {
        return ROLE.get();
    }

    /** 请求结束时无条件清理,防线程复用串租户 */
    public static void clear() {
        ORG_ID.remove();
        MEMBER_ID.remove();
        ROLE.remove();
    }
}
