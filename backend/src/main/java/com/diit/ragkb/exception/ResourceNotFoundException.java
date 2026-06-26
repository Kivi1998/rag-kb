package com.diit.ragkb.exception;

/**
 * 资源不存在(404) —— 含跨租户场景:对其他组织资源一律按不存在处理
 */
public class ResourceNotFoundException extends RuntimeException {
    public ResourceNotFoundException(String message) {
        super(message);
    }
}
