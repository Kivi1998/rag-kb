package com.diit.ragkb.exception;

/**
 * 同租户内角色权限不足(403)
 */
public class AccessDeniedException extends RuntimeException {
    public AccessDeniedException(String message) {
        super(message);
    }
}
