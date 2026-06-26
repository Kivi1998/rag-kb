package com.diit.ragkb.model;

/**
 * 文档解析状态
 *
 * UPLOADING: 已落库,文件正在推送/触发解析
 * PARSING:   RAGFlow 已接收并开始解析
 * READY:     解析完成,可用于 RAG 问答(终态)
 * FAILED:    上传或解析失败(终态)
 */
public enum DocumentStatus {
    UPLOADING,
    PARSING,
    READY,
    FAILED
}
