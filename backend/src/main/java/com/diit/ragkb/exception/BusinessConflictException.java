package com.diit.ragkb.exception;

/**
 * 业务不变量冲突(409) —— 如:降级最后一名 owner
 */
public class BusinessConflictException extends RuntimeException {
    public BusinessConflictException(String message) {
        super(message);
    }
}
