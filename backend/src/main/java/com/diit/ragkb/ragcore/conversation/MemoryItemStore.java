package com.diit.ragkb.ragcore.conversation;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

/**
 * 用户画像条目（{@code memory_items}）的读写端口：语义去重、读时衰减、检索命中巩固。
 */
public interface MemoryItemStore {

    /** 语义去重检索：与已有条目相似度超过阈值时返回最相似的一条，供调用方决定合并/跳过；否则返回空。 */
    Optional<MemoryItemDocument> findSimilarExisting(UUID organizationId, UUID memberId, List<Float> candidateVector);

    /** 新增一条画像条目（MongoDB + 统一记忆索引同步写入）。 */
    MemoryItemDocument createItem(UUID organizationId, UUID memberId, String type, String content,
                                  double initialImportance, List<Float> vector, UUID sourceSessionId);

    /**
     * 按 {@code effective_importance = importance × decay(now - lastAccessedAt)} 排序取 top-K 画像条目；
     * 命中的条目会被巩固（更新 accessCount/lastAccessedAt）。
     */
    List<MemoryItemDocument> topKForGeneration(UUID organizationId, UUID memberId, List<Float> queryVector, int topK);

    /** 低优先级定期清理：物理删除长期未访问且重要度低于阈值的条目，不影响功能正确性，纯空间优化。 */
    int cleanupStale(Instant cutoff, double importanceThreshold);
}
