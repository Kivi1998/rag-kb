package com.diit.ragkb.ragcore.conversation.impl;

import com.diit.ragkb.config.RagMemoryProperties;
import com.diit.ragkb.ragcore.conversation.MemoryItemStore;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;

import java.time.Instant;
import java.time.temporal.ChronoUnit;

/**
 * 低优先级定期清理：物理删除长期未访问且重要度低的画像条目。纯粹是空间优化，
 * 即使这个任务从未运行，检索结果依然正确（低权重条目本来就排不进 top-K）。
 */
@Slf4j
@RequiredArgsConstructor
public class MemoryCleanupTask {

    private static final double CLEANUP_IMPORTANCE_THRESHOLD = 0.05;

    private final MemoryItemStore memoryItemStore;
    private final RagMemoryProperties properties;

    @Scheduled(fixedDelayString = "${rag.memory.cleanup-interval-ms:86400000}")
    public void cleanup() {
        Instant cutoff = Instant.now().minus(3L * properties.getDecayHalfLifeDays(), ChronoUnit.DAYS);
        int deleted = memoryItemStore.cleanupStale(cutoff, CLEANUP_IMPORTANCE_THRESHOLD);
        if (deleted > 0) {
            log.info("画像记忆定期清理完成，删除 {} 条长期低权重条目", deleted);
        }
    }
}
