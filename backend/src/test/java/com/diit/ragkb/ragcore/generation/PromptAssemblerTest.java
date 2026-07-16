package com.diit.ragkb.ragcore.generation;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertTrue;

class PromptAssemblerTest {

    private final PromptAssembler assembler = new PromptAssembler();

    @Test
    void systemPromptRequiresFoundJsonPrefixLine() {
        String prompt = assembler.systemPrompt();

        assertTrue(prompt.contains("{\"found\": true}"));
        assertTrue(prompt.contains("{\"found\": false}"));
        assertTrue(prompt.contains("只能依据给出的参考资料回答"));
    }

    @Test
    void additionalContextAppendedAfterBasePrompt() {
        String prompt = assembler.systemPrompt("用户画像：偏好简洁回答");

        assertTrue(prompt.startsWith("你是企业技术文档助手"));
        assertTrue(prompt.endsWith("用户画像：偏好简洁回答"));
    }

    @Test
    void systemPromptIncludesLengthAndToneGuidance() {
        String prompt = assembler.systemPrompt();

        assertTrue(prompt.contains("3-5 句话以内"));
        assertTrue(prompt.contains("面向内部同事"));
    }

    @Test
    void systemPromptIncludesFewShotExamplesCoveringBothFoundBranches() {
        String prompt = assembler.systemPrompt();

        assertTrue(prompt.contains("示例1"));
        assertTrue(prompt.contains("示例2"));
        assertTrue(prompt.contains("不是真实知识库内容"));
        assertTrue(prompt.contains("JWT 黑名单存的是 Redis"));
    }

    @Test
    void systemPromptIncludesMultiPassageFusionGuidance() {
        String prompt = assembler.systemPrompt();

        assertTrue(prompt.contains("已按相关性从高到低排序"));
        assertTrue(prompt.contains("优先采信排序更靠前、相关性更高的资料"));
    }
}
