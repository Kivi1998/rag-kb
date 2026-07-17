package com.diit.ragkb.ragcore.intent;

import com.diit.ragkb.ragcore.generation.ChatCompletionClient;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class LlmQueryIntentClassifierTest {

    @Test
    void parsesAllFourLegalLabelsCaseInsensitively() {
        ChatCompletionClient client = mock(ChatCompletionClient.class);
        LlmQueryIntentClassifier classifier = new LlmQueryIntentClassifier(client);

        when(client.complete(any(), any())).thenReturn("precise-lookup");
        assertEquals(QueryIntent.PRECISE_LOOKUP, classifier.classify("NullPointerException 怎么排查？"));

        when(client.complete(any(), any())).thenReturn("  SEMANTIC \n");
        assertEquals(QueryIntent.SEMANTIC, classifier.classify("为什么要用 L1 范数？"));

        when(client.complete(any(), any())).thenReturn("Comparative");
        assertEquals(QueryIntent.COMPARATIVE, classifier.classify("RPCA 和 PCA 的区别是什么？"));

        when(client.complete(any(), any())).thenReturn("out-of-scope");
        assertEquals(QueryIntent.OUT_OF_SCOPE, classifier.classify("今天天气怎么样？"));
    }

    @Test
    void unparsableOutputFallsBackToUnknown() {
        ChatCompletionClient client = mock(ChatCompletionClient.class);
        LlmQueryIntentClassifier classifier = new LlmQueryIntentClassifier(client);

        when(client.complete(any(), any())).thenReturn("这应该属于精确检索型相关问题~");
        assertEquals(QueryIntent.UNKNOWN, classifier.classify("问题"));

        when(client.complete(any(), any())).thenReturn("");
        assertEquals(QueryIntent.UNKNOWN, classifier.classify("问题"));

        when(client.complete(any(), any())).thenReturn((String) null);
        assertEquals(QueryIntent.UNKNOWN, classifier.classify("问题"));
    }

    @Test
    void exceptionFromClientFailsOpenToUnknownWithoutPropagating() {
        ChatCompletionClient client = mock(ChatCompletionClient.class);
        when(client.complete(any(), any())).thenThrow(new RuntimeException("模型超时"));
        LlmQueryIntentClassifier classifier = new LlmQueryIntentClassifier(client);

        assertEquals(QueryIntent.UNKNOWN, classifier.classify("问题"));
    }

    @Test
    void blankQuestionIsUnknownWithoutCallingModel() {
        ChatCompletionClient client = mock(ChatCompletionClient.class);
        LlmQueryIntentClassifier classifier = new LlmQueryIntentClassifier(client);

        assertEquals(QueryIntent.UNKNOWN, classifier.classify(" "));
        assertEquals(QueryIntent.UNKNOWN, classifier.classify(null));
        verify(client, never()).complete(any(), any());
    }
}
