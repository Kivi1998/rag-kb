package com.diit.ragkb.model;

/**
 * 会话生命周期状态：ACTIVE(30分钟内有新消息) → IDLE(超过30分钟未超2小时) → ARCHIVED(超过2小时)
 * 有新消息时随时从 IDLE/ARCHIVED 续期回 ACTIVE。
 */
public enum ChatSessionStatus {
    ACTIVE,
    IDLE,
    ARCHIVED
}
