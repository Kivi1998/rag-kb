package com.diit.ragkb.ragcore.conversation.impl;

import com.diit.ragkb.ragcore.conversation.ChatMessage;
import com.diit.ragkb.ragcore.conversation.ConversationSummarizer;
import com.diit.ragkb.ragcore.generation.ChatCompletionClient;

import java.util.List;
import java.util.Objects;
import java.util.stream.Collectors;

/** 把超预算的最旧对话轮次压缩成一段摘要，供滑动窗口注入检索/生成上下文。 */
public class DeepSeekConversationSummarizer implements ConversationSummarizer {

    private static final String SYSTEM_PROMPT = "你是对话摘要助手。把下面这段对话历史压缩成一段简洁的摘要，"
            + "保留关键信息（讨论过的话题、结论、提到的具体名词），不要加入原文没有的内容，不要逐句翻译，直接输出摘要文本。";

    private final ChatCompletionClient chatCompletionClient;

    public DeepSeekConversationSummarizer(ChatCompletionClient chatCompletionClient) {
        this.chatCompletionClient = Objects.requireNonNull(chatCompletionClient, "chatCompletionClient 不能为空");
    }

    @Override
    public String summarize(List<ChatMessage> messagesToCompress) {
        if (messagesToCompress == null || messagesToCompress.isEmpty()) {
            return "";
        }
        String transcript = messagesToCompress.stream()
                .map(m -> ("user".equals(m.role()) ? "用户：" : "助手：") + m.content())
                .collect(Collectors.joining("\n"));
        return chatCompletionClient.complete(SYSTEM_PROMPT, transcript);
    }
}
