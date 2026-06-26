package com.diit.ragkb.exception;

/**
 * 未认证(401) —— 请求未携带有效身份凭证
 */
public class UnauthenticatedException extends RuntimeException {
    public UnauthenticatedException(String message) {
        super(message);
    }
}
