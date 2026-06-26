package com.diit.ragkb.model;

/**
 * 知识库状态
 */
public enum KbStatus {
    /** 正常 */
    ACTIVE,
    /** 待清理(dataset 删除失败,由对账任务处理) */
    PENDING_CLEANUP
}
