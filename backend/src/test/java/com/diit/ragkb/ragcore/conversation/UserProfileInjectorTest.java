package com.diit.ragkb.ragcore.conversation;

import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/** 画像只影响生成阶段的 System 上下文格式化，不接触任何检索组件（本类没有检索相关依赖）。 */
class UserProfileInjectorTest {

    private final UUID orgId = UUID.randomUUID();
    private final UUID memberId = UUID.randomUUID();
    private final List<Float> vector = List.of(0.1f, 0.2f);

    @Test
    void noProfileItemsReturnsEmptyContext() {
        MemoryItemStore store = mock(MemoryItemStore.class);
        when(store.topKForGeneration(orgId, memberId, vector, 5)).thenReturn(List.of());
        UserProfileInjector injector = new UserProfileInjector(store, 5);

        String context = injector.buildSystemContext(orgId, memberId, vector);

        assertEquals("", context);
    }

    @Test
    void profileItemsAreFormattedAsSystemContext() {
        MemoryItemStore store = mock(MemoryItemStore.class);
        MemoryItemDocument goal = new MemoryItemDocument(memberId, orgId, "GOAL", "正在做 MinIO 迁移项目", 0.7,
                Instant.now(), null);
        when(store.topKForGeneration(orgId, memberId, vector, 5)).thenReturn(List.of(goal));
        UserProfileInjector injector = new UserProfileInjector(store, 5);

        String context = injector.buildSystemContext(orgId, memberId, vector);

        assertTrue(context.contains("正在做 MinIO 迁移项目"));
        assertTrue(context.contains("GOAL"));
    }
}
