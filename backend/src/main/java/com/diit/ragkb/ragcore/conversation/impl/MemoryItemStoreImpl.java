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

    /** 语义去重阈值：ES cosine kNN 场景下 _score 大致落在 0~1，超过此值视为重复。 */
    private static final double DEDUP_SIMILARITY_THRESHOLD = 0.92;

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
        if (candidates.isEmpty() || candidates.get(0).score() < DEDUP_SIMILARITY_THRESHOLD) {
            return Optional.empty();
        }
        String memoryId = candidates.get(0).record().memoryId();
        return memoryItemRepository.findById(memoryId);
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
        List<MemoryItemDocument> scored = new ArrayList<>();
        Instant now = Instant.now();
        for (MemoryIndex.ScoredMemoryRecord candidate : candidates) {
            memoryItemRepository.findById(candidate.record().memoryId()).ifPresent(scored::add);
        }
        scored.sort(Comparator.comparingDouble((MemoryItemDocument doc) -> effectiveImportance(doc, now)).reversed());
        List<MemoryItemDocument> selected = scored.stream().limit(topK).toList();
        for (MemoryItemDocument document : selected) {
            reinforce(document, now);
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

    private void reinforce(MemoryItemDocument document, Instant now) {
        document.setAccessCount(document.getAccessCount() + 1);
        document.setLastAccessedAt(now);
        memoryItemRepository.save(document);
    }

    /** effective_importance = importance × decay(now - lastAccessedAt)，decay 用半衰期指数衰减。 */
    private double effectiveImportance(MemoryItemDocument document, Instant now) {
        double daysSinceAccess = java.time.Duration.between(document.getLastAccessedAt(), now).toHours() / 24.0;
        double halfLifeDays = Math.max(1, properties.getDecayHalfLifeDays());
        double decay = Math.pow(0.5, daysSinceAccess / halfLifeDays);
        return document.getImportance() * decay;
    }
}
