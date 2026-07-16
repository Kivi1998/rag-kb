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
}
