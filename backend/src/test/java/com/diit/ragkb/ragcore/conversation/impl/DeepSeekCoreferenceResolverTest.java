package com.diit.ragkb.ragcore.conversation.impl;

import com.diit.ragkb.ragcore.conversation.ChatMessage;
import com.diit.ragkb.ragcore.generation.ChatCompletionClient;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/** 成功补全指代 / 调用失败降级 / 无历史时直接跳过调用。 */
class DeepSeekCoreferenceResolverTest {

    @Test
    void resolvesReferentialQuestionUsingHistory() {
        ChatCompletionClient client = mock(ChatCompletionClient.class);
        when(client.complete(any(), any())).thenReturn("重疾险犹豫期过了还能退保吗");
        DeepSeekCoreferenceResolver resolver = new DeepSeekCoreferenceResolver(client);
        List<ChatMessage> history = List.of(
                ChatMessage.user("这款重疾险的犹豫期是几天？", Instant.now()),
                ChatMessage.assistant("犹豫期为 15 天", Instant.now()));

        String resolved = resolver.resolve("那它过了还能退吗", history);

        assertEquals("重疾险犹豫期过了还能退保吗", resolved);
    }

    @Test
    void degradesToOriginalQuestionOnFailure() {
        ChatCompletionClient client = mock(ChatCompletionClient.class);
        when(client.complete(any(), any())).thenThrow(new RuntimeException("模型调用超时"));
        DeepSeekCoreferenceResolver resolver = new DeepSeekCoreferenceResolver(client);
        List<ChatMessage> history = List.of(ChatMessage.user("上一个问题", Instant.now()));

        String resolved = resolver.resolve("那它过了还能退吗", history);

        assertEquals("那它过了还能退吗", resolved);
    }

    @Test
    void noHistorySkipsLlmCallEntirely() {
        ChatCompletionClient client = mock(ChatCompletionClient.class);
        DeepSeekCoreferenceResolver resolver = new DeepSeekCoreferenceResolver(client);

        String resolved = resolver.resolve("NullPointerException 怎么排查", List.of());

        assertEquals("NullPointerException 怎么排查", resolved);
        org.mockito.Mockito.verifyNoInteractions(client);
    }
}
