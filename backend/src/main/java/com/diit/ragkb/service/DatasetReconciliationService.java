package com.diit.ragkb.service;

import com.diit.ragkb.model.KbStatus;
import com.diit.ragkb.model.KnowledgeBase;
import com.diit.ragkb.repository.KnowledgeBaseRepository;
import com.diit.ragkb.service.ragflow.RagFlowClient;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;

/**
 * 孤儿 dataset 对账服务
 *
 * 职责:
 * 1. 处理 status=PENDING_CLEANUP 的知识库(dataset 删除失败转来)
 * 2. 清理无对应知识库的 RAGFlow dataset(仅限带本产品归属前缀且超 grace period)
 *
 * 触发:定时任务或手动调用
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DatasetReconciliationService {

    private final KnowledgeBaseRepository kbRepository;
    private final RagFlowClient ragFlowClient;

    /** grace period:创建时间超过此阈值且无有效映射的 dataset 才清理(避开创建中竞态) */
    private static final long GRACE_PERIOD_MINUTES = 30;

    /**
     * 处理 PENDING_CLEANUP 的知识库
     */
    @Transactional
    public int reconcilePendingCleanup() {
        List<KnowledgeBase> pendingList = kbRepository.findByStatus(KbStatus.PENDING_CLEANUP);
        int cleaned = 0;

        for (KnowledgeBase kb : pendingList) {
            try {
                if (kb.getRagflowDatasetId() != null) {
                    ragFlowClient.deleteDataset(kb.getRagflowDatasetId());
                    log.info("对账:dataset 清理成功,kbId={},datasetId={}", kb.getId(), kb.getRagflowDatasetId());
                }
                kbRepository.delete(kb);
                cleaned++;
            } catch (Exception e) {
                log.warn("对账:dataset 清理仍失败,kbId={}: {}", kb.getId(), e.getMessage());
            }
        }

        log.info("对账完成:处理 {} 条 PENDING_CLEANUP,成功清理 {} 条", pendingList.size(), cleaned);
        return cleaned;
    }

    /**
     * 检查孤儿:知识库记录已删但 dataset 仍在
     * 注:需 RAGFlow API 支持按标签/前缀查询,此处为占位实现
     *
     * 实际实现需:
     * 1. 列出 RAGFlow 所有 dataset
     * 2. 筛选 description 带 "ragkb:" 前缀的
     * 3. 超 grace period 且无对应知识库记录的 → 删除
     */
    public void cleanOrphanDatasets() {
        // TODO: 需 RAGFlow 列表 dataset API 支持后实现
        // 占位:记录日志,后续迭代补充
        log.info("孤儿 dataset 扫描(待 RAGFlow API 支持后实现)");
    }
}
