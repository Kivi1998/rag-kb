package com.diit.ragkb.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;

/**
 * 问答请求体
 */
@Data
public class QueryRequest {

    /** 问题(必填) */
    @NotBlank(message = "问题不能为空")
    private String question;

    /** 返回引用来源数量(默认 5,范围 1-20) */
    @Min(value = 1, message = "topN 最小为 1")
    @Max(value = 20, message = "topN 最大为 20")
    private int topN = 5;
}
