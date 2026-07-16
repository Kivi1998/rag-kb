package com.diit.ragkb.ragcore.conversation.impl;

import com.diit.ragkb.ragcore.conversation.MemoryItemDocument;
import com.diit.ragkb.ragcore.conversation.MemoryItemStore;
import com.diit.ragkb.ragcore.embedding.EmbeddingClient;
import com.diit.ragkb.ragcore.generation.ChatCompletionClient;
import com.diit.ragkb.ragcore.model.EmbeddingResult;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/** 新增画像条目 / 语义去重跳过 / 提炼失败不影响已返回回答（不向调用方抛异常）。 */
class DeepSeekMemoryExtractorTest {

    private ChatCompletionClient chatCompletionClient;
    private EmbeddingClient embeddingClient;
    private MemoryItemStore memoryItemStore;
    private DeepSeekMemoryExtractor extractor;

    private final UUID orgId = UUID.randomUUID();
    private final UUID memberId = UUID.randomUUID();
    private final UUID sessionId = UUID.randomUUID();

    @BeforeEach
    void setUp() {
        chatCompletionClient = mock(ChatCompletionClient.class);
        embeddingClient = mock(EmbeddingClient.class);
        memoryItemStore = mock(MemoryItemStore.class);
        extractor = new DeepSeekMemoryExtractor(chatCompletionClient, embeddingClient, memoryItemStore,
                new ObjectMapper());
        when(embeddingClient.embed(any())).thenReturn(new EmbeddingResult("model", List.of(List.of(0.1f, 0.2f))));
    }

    @Test
    void extractsAndStoresNewCandidateWhenNotSimilar() {
        when(chatCompletionClient.complete(any(), any())).thenReturn(
                "{\"items\":[{\"type\":\"GOAL\",\"content\":\"正在做 MinIO 迁移项目\",\"importance\":0.7}]}");
        when(memoryItemStore.findSimilarExisting(any(), any(), any())).thenReturn(Optional.empty());

        extractor.extractAndStore(orgId, memberId, sessionId, "问题", "回答");

        verify(memoryItemStore, times(1)).createItem(orgId, memberId, "GOAL", "正在做 MinIO 迁移项目", 0.7,
                List.of(0.1f, 0.2f), sessionId);
    }

    @Test
    void skipsCandidateWhenSemanticallySimilarExists() {
        when(chatCompletionClient.complete(any(), any())).thenReturn(
                "{\"items\":[{\"type\":\"FACT\",\"content\":\"已投保重疾险\",\"importance\":0.6}]}");
        MemoryItemDocument existing = new MemoryItemDocument(memberId, orgId, "FACT", "已投保重疾险", 0.6, Instant.now(),
                null);
        when(memoryItemStore.findSimilarExisting(orgId, memberId, List.of(0.1f, 0.2f)))
                .thenReturn(Optional.of(existing));

        extractor.extractAndStore(orgId, memberId, sessionId, "问题", "回答");

        verify(memoryItemStore, never()).createItem(any(), any(), any(), any(), anyDouble(), any(), any());
    }

    @Test
    void emptyItemsArrayDoesNothing() {
        when(chatCompletionClient.complete(any(), any())).thenReturn("{\"items\":[]}");

        assertDoesNotThrow(() -> extractor.extractAndStore(orgId, memberId, sessionId, "问题", "回答"));

        verify(memoryItemStore, never()).createItem(any(), any(), any(), any(), anyDouble(), any(), any());
    }

    @Test
    void llmFailureDoesNotPropagateException() {
        when(chatCompletionClient.complete(any(), any())).thenThrow(new RuntimeException("模型调用失败"));

        assertDoesNotThrow(() -> extractor.extractAndStore(orgId, memberId, sessionId, "问题", "回答"));
    }

    @Test
    void malformedJsonResponseDoesNotPropagateException() {
        when(chatCompletionClient.complete(any(), any())).thenReturn("这不是合法的 JSON");

        assertDoesNotThrow(() -> extractor.extractAndStore(orgId, memberId, sessionId, "问题", "回答"));
    }
}
