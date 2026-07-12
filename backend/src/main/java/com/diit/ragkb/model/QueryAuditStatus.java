package com.diit.ragkb.model;

/** 问答审计最终状态；客户端中断与系统失败须区分。 */
public enum QueryAuditStatus {
    COMPLETED,
    REFUSED,
    FAILED,
    CANCELLED
}
