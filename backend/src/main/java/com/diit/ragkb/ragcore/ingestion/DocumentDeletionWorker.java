package com.diit.ragkb.ragcore.ingestion;

import lombok.RequiredArgsConstructor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/** 对 DELETING 文档执行幂等清理，覆盖 ES 或对象存储的短暂失败。 */
@Component
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "rag.ingestion.cleanup", name = "enabled", havingValue = "true", matchIfMissing = true)
public class DocumentDeletionWorker {

    private final DocumentDeletionService deletionService;

    @Scheduled(fixedDelayString = "${rag.ingestion.cleanup.poll-interval-ms:30000}")
    public void retryPendingDeletions() {
        deletionService.pendingDeletionIds(20).forEach(deletionService::cleanup);
    }
}
