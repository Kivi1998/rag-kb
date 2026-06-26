package com.diit.ragkb.exception;

/**
 * 账号已锁定(423 Locked)
 */
public class AccountLockedException extends RuntimeException {
    public AccountLockedException(String message) {
        super(message);
    }
}
