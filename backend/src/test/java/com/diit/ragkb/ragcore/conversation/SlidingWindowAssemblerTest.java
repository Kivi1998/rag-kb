package com.diit.ragkb.ragcore.conversation;

import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/** 预算内不触发摘要 / 超预算触发摘要压缩 / 关键事实消息不参与压缩。 */
class SlidingWindowAssemblerTest {

    @Test
    void withinBudgetDoesNotTriggerSummary() {
        RecordingSummarizer summarizer = new RecordingSummarizer();
        SlidingWindowAssembler assembler = new SlidingWindowAssembler(summarizer);
        List<ChatMessage> messages = List.of(
                ChatMessage.user("你好", Instant.now()),
                ChatMessage.assistant("你好，有什么可以帮你", Instant.now()));

        ConversationWindow window = assembler.assemble(messages, 1000);

        assertFalse(window.hasSummary());
        assertEquals(2, window.recentMessages().size());
        assertEquals(0, summarizer.callCount);
    }

    @Test
    void exceedingBudgetTriggersSummaryForOldestMessages() {
        RecordingSummarizer summarizer = new RecordingSummarizer();
        summarizer.summaryToReturn = "摘要：讨论了重疾险等待期";
        SlidingWindowAssembler assembler = new SlidingWindowAssembler(summarizer);
        // 每条约 300 汉字 token，预算 50：只有最近一条（9 token）能塞进窗口，其余都要被压缩。
        String longText = "重".repeat(300);
        List<ChatMessage> messages = List.of(
                ChatMessage.user(longText + "1", Instant.parse("2026-07-15T00:00:00Z")),
                ChatMessage.assistant(longText + "2", Instant.parse("2026-07-15T00:01:00Z")),
                ChatMessage.user("那它过了还能退吗", Instant.parse("2026-07-15T00:02:00Z")));

        ConversationWindow window = assembler.assemble(messages, 50);

        assertTrue(window.hasSummary());
        assertEquals("摘要：讨论了重疾险等待期", window.summary());
        assertEquals(1, summarizer.callCount);
        assertEquals(1, window.recentMessages().size());
        assertEquals("那它过了还能退吗", window.recentMessages().get(0).content());
        // 被压缩的是最旧的两条，按时间顺序传给 summarizer。
        assertEquals(2, summarizer.lastCompressedBatch.size());
        assertTrue(summarizer.lastCompressedBatch.get(0).content().endsWith("1"));
    }

    @Test
    void keyFactMessagesAreNeverCompressed() {
        RecordingSummarizer summarizer = new RecordingSummarizer();
        summarizer.summaryToReturn = "摘要";
        SlidingWindowAssembler assembler = new SlidingWindowAssembler(summarizer);
        String longText = "重".repeat(300);
        ChatMessage keyFact = new ChatMessage("user", "关键事实：本人已投保重疾险", true,
                Instant.parse("2026-07-15T00:00:00Z"));
        List<ChatMessage> messages = List.of(
                keyFact,
                ChatMessage.assistant(longText, Instant.parse("2026-07-15T00:01:00Z")),
                ChatMessage.user("最近的问题", Instant.parse("2026-07-15T00:02:00Z")));

        ConversationWindow window = assembler.assemble(messages, 100);

        assertTrue(window.recentMessages().contains(keyFact), "关键事实消息必须保留在 recentMessages 里，不参与压缩");
        assertFalse(summarizer.lastCompressedBatch.contains(keyFact), "关键事实消息不应出现在被压缩的批次里");
    }

    private static final class RecordingSummarizer implements ConversationSummarizer {
        int callCount = 0;
        String summaryToReturn = "";
        List<ChatMessage> lastCompressedBatch = List.of();

        @Override
        public String summarize(List<ChatMessage> messagesToCompress) {
            callCount++;
            lastCompressedBatch = messagesToCompress;
            return summaryToReturn;
        }
    }
}
