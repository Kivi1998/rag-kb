package com.diit.ragkb.ragcore.conversation;

import lombok.extern.slf4j.Slf4j;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Objects;

/**
 * 按 token 预算圈定滑动窗口：从最近消息往前累加，超预算时用摘要压缩替换最旧的非关键事实消息，
 * 而非直接丢弃；关键事实消息始终保留原文，不计入被压缩的候选。
 *
 * <p>摘要压缩失败时 fail-open：退化为只保留窗口内消息、不带摘要，不向上抛异常——与
 * {@code ConversationStore}/{@code CoreferenceResolver} 等记忆子组件的降级语义保持一致，
 * 不应因为摘要 LLM 调用失败而让整个问答请求失败。</p>
 */
@Slf4j
public class SlidingWindowAssembler {

    private final ConversationSummarizer summarizer;

    public SlidingWindowAssembler(ConversationSummarizer summarizer) {
        this.summarizer = Objects.requireNonNull(summarizer, "summarizer 不能为空");
    }

    public ConversationWindow assemble(List<ChatMessage> messages, int tokenBudget) {
        if (messages == null || messages.isEmpty()) {
            return new ConversationWindow(null, List.of());
        }

        List<ChatMessage> kept = new ArrayList<>();
        List<ChatMessage> toCompress = new ArrayList<>();
        int runningTokens = 0;
        boolean budgetExceeded = false;

        for (int i = messages.size() - 1; i >= 0; i--) {
            ChatMessage message = messages.get(i);
            if (message.keyFact()) {
                kept.add(message);
                continue;
            }
            if (!budgetExceeded) {
                int tokens = TokenEstimator.estimate(message.content());
                if (runningTokens + tokens <= tokenBudget) {
                    kept.add(message);
                    runningTokens += tokens;
                    continue;
                }
                budgetExceeded = true;
            }
            toCompress.add(message);
        }

        Collections.reverse(kept);
        Collections.reverse(toCompress);

        if (toCompress.isEmpty()) {
            return new ConversationWindow(null, kept);
        }
        try {
            String summary = summarizer.summarize(toCompress);
            return new ConversationWindow(summary, kept);
        } catch (RuntimeException ex) {
            log.warn("摘要压缩失败，本轮跳过摘要，仅保留窗口内消息", ex);
            return new ConversationWindow(null, kept);
        }
    }
}
