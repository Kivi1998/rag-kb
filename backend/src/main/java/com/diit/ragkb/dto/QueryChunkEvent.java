package com.diit.ragkb.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * SSE 事件 DTO(复用同一结构,由事件类型区分字段)
 *
 * chunk 事件:content 非空
 * source 事件:documentName + content + score 非空
 * error 事件:message 非空
 * done 事件:所有字段为 null(空对象)
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class QueryChunkEvent {

    /** chunk 事件:答案片段 */
    private String content;

    /** source 事件:引用文档名 */
    private String documentName;

    /** source 事件:引用相关度分数 */
    private Double score;

    /** error 事件:错误描述 */
    private String message;

    // ===== 工厂方法 =====

    public static QueryChunkEvent chunk(String content) {
        QueryChunkEvent event = new QueryChunkEvent();
        event.setContent(content);
        return event;
    }

    public static QueryChunkEvent source(String documentName, String content, double score) {
        QueryChunkEvent event = new QueryChunkEvent();
        event.setDocumentName(documentName);
        event.setContent(content);
        event.setScore(score);
        return event;
    }

    public static QueryChunkEvent error(String message) {
        QueryChunkEvent event = new QueryChunkEvent();
        event.setMessage(message);
        return event;
    }

    public static QueryChunkEvent done() {
        return new QueryChunkEvent();
    }
}
