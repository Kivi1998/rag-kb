package com.diit.ragkb.ragcore.conversation.impl;

import com.diit.ragkb.config.RagMemoryProperties;
import com.diit.ragkb.ragcore.conversation.MemoryIndex;
import com.diit.ragkb.ragcore.conversation.MemoryItemDocument;
import com.diit.ragkb.ragcore.conversation.MemoryItemRepository;
import com.diit.ragkb.ragcore.conversation.MemoryRecord;
import com.diit.ragkb.ragcore.conversation.MemoryType;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/** 语义去重（含 ES cosine _score 归一化换算）、租户二次校验、读时衰减排序、命中巩固。 */
class MemoryItemStoreImplTest {

    private MemoryIndex memoryIndex;
    private MemoryItemRepository repository;
    private MemoryItemStoreImpl store;

    private final UUID orgId = UUID.randomUUID();
    private final UUID memberId = UUID.randomUUID();
    private final List<Float> vector = List.of(0.1f, 0.2f);

    @BeforeEach
    void setUp() {
        memoryIndex = mock(MemoryIndex.class);
        repository = mock(MemoryItemRepository.class);
        RagMemoryProperties properties = new RagMemoryProperties();
        properties.setDecayHalfLifeDays(30);
        store = new MemoryItemStoreImpl(memoryIndex, repository, properties);
    }

    @Test
    void findSimilarExistingReturnsEmptyBelowThreshold() {
        MemoryRecord record = new MemoryRecord("mem-1", orgId, memberId, null, MemoryType.PROFILE_ITEM, "content",
                Instant.now());
        when(memoryIndex.searchProfileItems(orgId, memberId, vector, 1))
                .thenReturn(List.of(new MemoryIndex.ScoredMemoryRecord(record, 0.5)));

        Optional<MemoryItemDocument> result = store.findSimilarExisting(orgId, memberId, vector);

        assertTrue(result.isEmpty());
        verify(repository, never()).findById(any());
    }

    @Test
    void findSimilarExistingTreatsRawEsScoreNotRawCosineAsThreshold() {
        // 回归测试：ES cosine kNN 的 _score = (1+cosine)/2，0.94 曾经会被误判为超过 0.92 阈值触发去重，
        // 但换算成原始余弦阈值 0.92 后对应的 _score 应为 0.96，0.94 不应再命中去重。
        MemoryRecord record = new MemoryRecord("mem-1", orgId, memberId, null, MemoryType.PROFILE_ITEM, "content",
                Instant.now());
        when(memoryIndex.searchProfileItems(orgId, memberId, vector, 1))
                .thenReturn(List.of(new MemoryIndex.ScoredMemoryRecord(record, 0.94)));

        Optional<MemoryItemDocument> result = store.findSimilarExisting(orgId, memberId, vector);

        assertTrue(result.isEmpty(), "_score 0.94 换算成原始余弦约 0.88，不应被判定为重复");
        verify(repository, never()).findById(any());
    }

    @Test
    void findSimilarExistingReturnsMatchAboveThreshold() {
        MemoryRecord record = new MemoryRecord("mem-1", orgId, memberId, null, MemoryType.PROFILE_ITEM, "content",
                Instant.now());
        MemoryItemDocument existing = new MemoryItemDocument(memberId, orgId, "FACT", "content", 0.8, Instant.now(),
                null);
        when(memoryIndex.searchProfileItems(orgId, memberId, vector, 1))
                .thenReturn(List.of(new MemoryIndex.ScoredMemoryRecord(record, 0.97)));
        when(repository.findById("mem-1")).thenReturn(Optional.of(existing));

        Optional<MemoryItemDocument> result = store.findSimilarExisting(orgId, memberId, vector);

        assertTrue(result.isPresent());
    }

    @Test
    void findSimilarExistingRejectsCrossTenantDocumentEvenIfEsMatched() {
        // 回归测试：即使 ES 过滤出错返回了别的租户的 memory_id，MongoDB 层也必须二次校验拒绝返回。
        MemoryRecord record = new MemoryRecord("mem-1", orgId, memberId, null, MemoryType.PROFILE_ITEM, "content",
                Instant.now());
        MemoryItemDocument foreignTenantDoc = new MemoryItemDocument(UUID.randomUUID(), UUID.randomUUID(), "FACT",
                "别的租户的画像", 0.8, Instant.now(), null);
        when(memoryIndex.searchProfileItems(orgId, memberId, vector, 1))
                .thenReturn(List.of(new MemoryIndex.ScoredMemoryRecord(record, 0.99)));
        when(repository.findById("mem-1")).thenReturn(Optional.of(foreignTenantDoc));

        Optional<MemoryItemDocument> result = store.findSimilarExisting(orgId, memberId, vector);

        assertTrue(result.isEmpty(), "跨租户文档必须被二次校验拦截，即使 ES 侧过滤失效");
    }

    @Test
    void createItemWritesToMongoAndMemoryIndex() {
        when(repository.save(any(MemoryItemDocument.class))).thenAnswer(inv -> {
            MemoryItemDocument doc = inv.getArgument(0);
            doc.setId("mem-new");
            return doc;
        });

        MemoryItemDocument created = store.createItem(orgId, memberId, "GOAL", "正在做 MinIO 迁移项目", 0.7, vector, null);

        assertEquals("mem-new", created.getId());
        verify(memoryIndex, times(1)).upsert(any(MemoryRecord.class), eq(vector));
    }

    @Test
    void topKForGenerationOrdersByEffectiveImportanceNotRawImportance() {
        // 条目A：importance 高但很久没用；条目B：importance 略低但最近刚用过 —— B 的 effective_importance 应更高。
        MemoryRecord recordA = new MemoryRecord("mem-a", orgId, memberId, null, MemoryType.PROFILE_ITEM, "偏好A",
                Instant.now());
        MemoryRecord recordB = new MemoryRecord("mem-b", orgId, memberId, null, MemoryType.PROFILE_ITEM, "偏好B",
                Instant.now());
        MemoryItemDocument docA = new MemoryItemDocument(memberId, orgId, "PREFERENCE", "偏好A", 0.9,
                Instant.now().minus(120, ChronoUnit.DAYS), null); // 久未使用：120天，远超半衰期30天
        docA.setId("mem-a");
        MemoryItemDocument docB = new MemoryItemDocument(memberId, orgId, "PREFERENCE", "偏好B", 0.6,
                Instant.now(), null); // 刚刚使用
        docB.setId("mem-b");

        when(memoryIndex.searchProfileItems(orgId, memberId, vector, 10)).thenReturn(List.of(
                new MemoryIndex.ScoredMemoryRecord(recordA, 0.8),
                new MemoryIndex.ScoredMemoryRecord(recordB, 0.8)));
        when(repository.findAllById(List.of("mem-a", "mem-b"))).thenReturn(List.of(docA, docB));

        List<MemoryItemDocument> top = store.topKForGeneration(orgId, memberId, vector, 1);

        assertEquals(1, top.size());
        assertEquals("mem-b", top.get(0).getId(), "久未使用条目的 effective_importance 应因衰减低于近期使用的条目");
    }

    @Test
    void topKForGenerationReinforcesHitItemsWithBatchedSave() {
        MemoryRecord record = new MemoryRecord("mem-a", orgId, memberId, null, MemoryType.PROFILE_ITEM, "偏好A",
                Instant.now());
        MemoryItemDocument doc = new MemoryItemDocument(memberId, orgId, "PREFERENCE", "偏好A", 0.5, Instant.now(),
                null);
        doc.setId("mem-a");
        when(memoryIndex.searchProfileItems(orgId, memberId, vector, 10))
                .thenReturn(List.of(new MemoryIndex.ScoredMemoryRecord(record, 0.9)));
        when(repository.findAllById(List.of("mem-a"))).thenReturn(List.of(doc));

        store.topKForGeneration(orgId, memberId, vector, 1);

        assertEquals(1, doc.getAccessCount());
        verify(repository, never()).save(any()); // 巩固写入必须走批量 saveAll，不能逐条 save
        verify(repository, times(1)).saveAll(List.of(doc));
    }

    @Test
    void topKForGenerationFiltersOutCrossTenantDocuments() {
        // 回归测试：即使 ES 返回了别的租户的候选（比如过滤失效），MongoDB 层也必须二次校验剔除。
        MemoryRecord record = new MemoryRecord("mem-x", orgId, memberId, null, MemoryType.PROFILE_ITEM, "偏好X",
                Instant.now());
        MemoryItemDocument foreignTenantDoc = new MemoryItemDocument(UUID.randomUUID(), UUID.randomUUID(),
                "PREFERENCE", "别的租户的画像", 0.9, Instant.now(), null);
        foreignTenantDoc.setId("mem-x");
        when(memoryIndex.searchProfileItems(orgId, memberId, vector, 10))
                .thenReturn(List.of(new MemoryIndex.ScoredMemoryRecord(record, 0.9)));
        when(repository.findAllById(List.of("mem-x"))).thenReturn(List.of(foreignTenantDoc));

        List<MemoryItemDocument> top = store.topKForGeneration(orgId, memberId, vector, 1);

        assertTrue(top.isEmpty(), "跨租户文档必须被二次校验剔除");
    }

    @Test
    void cleanupStaleDeletesFromBothStores() {
        MemoryItemDocument stale = new MemoryItemDocument(memberId, orgId, "FACT", "旧事实", 0.01,
                Instant.now().minus(200, ChronoUnit.DAYS), null);
        stale.setId("mem-stale");
        Instant cutoff = Instant.now().minus(90, ChronoUnit.DAYS);
        when(repository.findByLastAccessedAtBeforeAndImportanceLessThan(cutoff, 0.1)).thenReturn(List.of(stale));

        int deleted = store.cleanupStale(cutoff, 0.1);

        assertEquals(1, deleted);
        verify(memoryIndex, times(1)).delete("mem-stale");
        verify(repository, times(1)).deleteById("mem-stale");
    }
}
