package com.diit.ragkb.ragcore.conversation;

import com.diit.ragkb.ragcore.embedding.EmbeddingClient;
import com.diit.ragkb.ragcore.model.EmbeddingResult;
import lombok.extern.slf4j.Slf4j;

import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;

/**
 * 记忆子系统的编排入口：检索前准备（滑动窗口→指代消解→画像检索），生成后记录
 * （写直达持久化 + 异步画像提炼）。是 {@code QueryService} 与记忆各组件之间的唯一接触面，
 * QueryService 只依赖这一个类（通过 {@code ObjectProvider} 可选注入），不需要单独认识
 * 六七个记忆相关组件。
 */
@Slf4j
public class ConversationMemoryOrchestrator {

    private final ConversationStore conversationStore;
    private final SlidingWindowAssembler slidingWindowAssembler;
    private final CoreferenceResolver coreferenceResolver;
    private final EmbeddingClient embeddingClient;
    private final UserProfileInjector userProfileInjector;
    private final MemoryExtractor memoryExtractor;
    private final int tokenBudget;

    public ConversationMemoryOrchestrator(ConversationStore conversationStore,
                                          SlidingWindowAssembler slidingWindowAssembler,
                                          CoreferenceResolver coreferenceResolver, EmbeddingClient embeddingClient,
                                          UserProfileInjector userProfileInjector, MemoryExtractor memoryExtractor,
                                          int tokenBudget) {
        this.conversationStore = Objects.requireNonNull(conversationStore);
        this.slidingWindowAssembler = Objects.requireNonNull(slidingWindowAssembler);
        this.coreferenceResolver = Objects.requireNonNull(coreferenceResolver);
        this.embeddingClient = Objects.requireNonNull(embeddingClient);
        this.userProfileInjector = Objects.requireNonNull(userProfileInjector);
        this.memoryExtractor = Objects.requireNonNull(memoryExtractor);
        this.tokenBudget = tokenBudget;
    }

    public MemoryContext prepareContext(UUID organizationId, UUID memberId, UUID sessionId, String question) {
        List<ChatMessage> recentRaw = conversationStore.recentRawMessages(organizationId, sessionId);
        ConversationWindow window = slidingWindowAssembler.assemble(recentRaw, tokenBudget);
        String resolvedQuestion = coreferenceResolver.resolve(question, window.recentMessages());

        String profileContext = "";
        List<Float> resolvedQuestionVector = null;
        try {
            EmbeddingResult embedding = embeddingClient.embed(List.of(resolvedQuestion));
            if (!embedding.vectors().isEmpty()) {
                resolvedQuestionVector = embedding.vectors().get(0);
                profileContext = userProfileInjector.buildSystemContext(organizationId, memberId,
                        resolvedQuestionVector);
            }
        } catch (RuntimeException ex) {
            log.warn("记忆检索用的向量化失败，本轮跳过画像注入: sessionId={}", sessionId, ex);
        }
        // 把这里算好的向量带给检索阶段复用，避免同一句 resolvedQuestion 被检索链路重复调用 Embedding。
        return new MemoryContext(resolvedQuestion, profileContext, resolvedQuestionVector);
    }

    /** 写直达持久化本轮问答 + 异步触发画像提炼；不抛异常，失败只记日志。 */
    public void recordTurn(UUID organizationId, UUID kbId, UUID memberId, UUID sessionId, String question,
                           String answer) {
        try {
            Instant now = Instant.now();
            conversationStore.appendMessage(organizationId, kbId, memberId, sessionId,
                    ChatMessage.user(question, now));
            conversationStore.appendMessage(organizationId, kbId, memberId, sessionId,
                    ChatMessage.assistant(answer, now));
        } catch (RuntimeException ex) {
            log.warn("会话消息持久化失败，不影响已返回给用户的回答: sessionId={}", sessionId, ex);
        }
        CompletableFuture.runAsync(() -> memoryExtractor.extractAndStore(organizationId, memberId, sessionId,
                question, answer));
    }
}
