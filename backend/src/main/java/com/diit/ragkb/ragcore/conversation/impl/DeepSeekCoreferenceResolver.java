package com.diit.ragkb.ragcore.conversation.impl;

import com.diit.ragkb.ragcore.conversation.ChatMessage;
import com.diit.ragkb.ragcore.conversation.CoreferenceResolver;
import com.diit.ragkb.ragcore.generation.ChatCompletionClient;
import lombok.extern.slf4j.Slf4j;

import java.util.List;
import java.util.Objects;
import java.util.stream.Collectors;

/**
 * 窄范围指代消解：prompt 严格限定"只做指代/省略补全，禁止改写技术术语、错误码、配置项等专有名词"。
 * 调用失败或超时时 fail-open，直接返回原始问题，不阻断问答主流程。
 */
@Slf4j
public class DeepSeekCoreferenceResolver implements CoreferenceResolver {

    private static final String SYSTEM_PROMPT = "你的唯一任务是指代消解：结合对话历史，把用户最新问题里的代词"
            + "（它/这个/那个/上面说的 等）或省略部分补全，使其成为一句不看历史也能理解的独立问题。"
            + "严格禁止：不要改写、翻译或润色任何技术术语、类名、错误码、配置项、专有名词；"
            + "如果问题本身不含任何指代，原样输出，不做任何改动。只输出补全后的问题，不要输出解释。";

    private final ChatCompletionClient chatCompletionClient;

    public DeepSeekCoreferenceResolver(ChatCompletionClient chatCompletionClient) {
        this.chatCompletionClient = Objects.requireNonNull(chatCompletionClient, "chatCompletionClient 不能为空");
    }

    @Override
    public String resolve(String question, List<ChatMessage> history) {
        if (history == null || history.isEmpty()) {
            return question;
        }
        try {
            String transcript = history.stream()
                    .map(m -> ("user".equals(m.role()) ? "用户：" : "助手：") + m.content())
                    .collect(Collectors.joining("\n"));
            String userPrompt = "对话历史：\n" + transcript + "\n\n用户最新问题：" + question;
            String resolved = chatCompletionClient.complete(SYSTEM_PROMPT, userPrompt);
            return resolved == null || resolved.isBlank() ? question : resolved.strip();
        } catch (RuntimeException ex) {
            log.warn("指代消解调用失败，退回原始问题继续检索: {}", ex.getMessage());
            return question;
        }
    }
}
