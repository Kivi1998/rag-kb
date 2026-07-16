package com.diit.ragkb.ragcore.conversation.impl;

import com.diit.ragkb.config.RagMemoryProperties;
import com.diit.ragkb.ragcore.conversation.MemoryIndex;
import com.diit.ragkb.ragcore.conversation.MemoryItemDocument;
import com.diit.ragkb.ragcore.conversation.MemoryItemRepository;
import com.diit.ragkb.ragcore.conversation.MemoryItemStore;
import com.diit.ragkb.ragcore.conversation.MemoryRecord;
import com.diit.ragkb.ragcore.conversation.MemoryType;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

/**
 * {@link MemoryItemStore} 实现：MongoDB 存权威数据（importance/accessCount/lastAccessedAt），
 * 统一记忆索引（ES）负责语义检索候选池，读时计算衰减，不需要定时批处理任务。
 */
public class MemoryItemStoreImpl implements MemoryItemStore {

    /**
     * 语义去重阈值，语义是"原始余弦相似度"，而非 ES 返回的 {@code _score}。
     *
     * <p>ES 对 {@code cosine} 相似度的 dense_vector 字段做了 {@code _score = (1 + cosine) / 2}
     * 归一化（保证非负），并非原始余弦值本身；直接拿原始余弦阈值与 {@code _score} 比较会让判定
     * 阈值变松（原始余弦 ~0.84 就会产生 {@code _score} ≈ 0.92），因此比较前必须先用
     * {@link #dedupScoreThreshold()} 换算成 {@code _score} 量纲。</p>
     */
    private static final double DEDUP_COSINE_SIMILARITY_THRESHOLD = 0.92;

    private final MemoryIndex memoryIndex;
    private final MemoryItemRepository memoryItemRepository;
    private final RagMemoryProperties properties;

    public MemoryItemStoreImpl(MemoryIndex memoryIndex, MemoryItemRepository memoryItemRepository,
                              RagMemoryProperties properties) {
        this.memoryIndex = Objects.requireNonNull(memoryIndex, "memoryIndex 不能为空");
        this.memoryItemRepository = Objects.requireNonNull(memoryItemRepository, "memoryItemRepository 不能为空");
        this.properties = Objects.requireNonNull(properties, "properties 不能为空");
    }

    @Override
    public Optional<MemoryItemDocument> findSimilarExisting(UUID organizationId, UUID memberId,
                                                            List<Float> candidateVector) {
        List<MemoryIndex.ScoredMemoryRecord> candidates =
                memoryIndex.searchProfileItems(organizationId, memberId, candidateVector, 1);
        if (candidates.isEmpty() || candidates.get(0).score() < dedupScoreThreshold()) {
            return Optional.empty();
        }
        String memoryId = candidates.get(0).record().memoryId();
        return memoryItemRepository.findById(memoryId)
                .filter(document -> belongsToTenant(document, organizationId, memberId));
    }

    /** 原始余弦阈值换算成 ES {@code _score} 量纲：{@code _score = (1 + cosine) / 2}。 */
    private static double dedupScoreThreshold() {
        return (1 + DEDUP_COSINE_SIMILARITY_THRESHOLD) / 2.0;
    }

    /**
     * 二次校验租户归属，不完全信任上游 ES kNN 过滤的结果——防止索引 bug、映射迁移等原因
     * 导致跨租户的 memory_id 被返回后，仍从 MongoDB 里读出并使用另一租户的画像数据。
     */
    private static boolean belongsToTenant(MemoryItemDocument document, UUID organizationId, UUID memberId) {
        return organizationId.equals(document.getOrganizationId()) && memberId.equals(document.getMemberId());
    }

    @Override
    public MemoryItemDocument createItem(UUID organizationId, UUID memberId, String type, String content,
                                         double initialImportance, List<Float> vector, UUID sourceSessionId) {
        Instant now = Instant.now();
        MemoryItemDocument document = new MemoryItemDocument(memberId, organizationId, type, content,
                initialImportance, now, sourceSessionId);
        document = memoryItemRepository.save(document);
        MemoryRecord record = new MemoryRecord(document.getId(), organizationId, memberId, null,
                MemoryType.PROFILE_ITEM, content, now);
        memoryIndex.upsert(record, vector);
        return document;
    }

    @Override
    public List<MemoryItemDocument> topKForGeneration(UUID organizationId, UUID memberId, List<Float> queryVector,
                                                       int topK) {
        // 候选池比 topK 更大：ES 只负责"语义相关"，最终排序还要叠加 effective_importance。
        List<MemoryIndex.ScoredMemoryRecord> candidates =
                memoryIndex.searchProfileItems(organizationId, memberId, queryVector, Math.max(topK * 3, 10));
        List<String> candidateIds = candidates.stream().map(candidate -> candidate.record().memoryId()).toList();
        Instant now = Instant.now();
        List<MemoryItemDocument> scored = new ArrayList<>();
        // 批量 findAllById 替代逐条 findById，避免每次问答产生 N 次串行 Mongo 往返；
        // 同时二次校验租户归属，不完全信任上游 ES 过滤结果。
        for (MemoryItemDocument document : memoryItemRepository.findAllById(candidateIds)) {
            if (belongsToTenant(document, organizationId, memberId)) {
                scored.add(document);
            }
        }
        scored.sort(Comparator.comparingDouble((MemoryItemDocument doc) -> effectiveImportance(doc, now)).reversed());
        List<MemoryItemDocument> selected = scored.stream().limit(topK).toList();
        selected.forEach(document -> reinforceInPlace(document, now));
        if (!selected.isEmpty()) {
            memoryItemRepository.saveAll(selected); // 批量落库，替代逐条 save
        }
        return selected;
    }

    @Override
    public int cleanupStale(Instant cutoff, double importanceThreshold) {
        List<MemoryItemDocument> stale =
                memoryItemRepository.findByLastAccessedAtBeforeAndImportanceLessThan(cutoff, importanceThreshold);
        for (MemoryItemDocument document : stale) {
            memoryIndex.delete(document.getId());
            memoryItemRepository.deleteById(document.getId());
        }
        return stale.size();
    }

    /** 只更新内存中的对象字段，落库交给调用方批量 saveAll，避免逐条 save 造成 N+1。 */
    private void reinforceInPlace(MemoryItemDocument document, Instant now) {
        document.setAccessCount(document.getAccessCount() + 1);
        document.setLastAccessedAt(now);
    }

    /** effective_importance = importance × decay(now - lastAccessedAt)，decay 用半衰期指数衰减。 */
    private double effectiveImportance(MemoryItemDocument document, Instant now) {
        double daysSinceAccess = java.time.Duration.between(document.getLastAccessedAt(), now).toHours() / 24.0;
        double halfLifeDays = Math.max(1, properties.getDecayHalfLifeDays());
        double decay = Math.pow(0.5, daysSinceAccess / halfLifeDays);
        return document.getImportance() * decay;
    }
}
