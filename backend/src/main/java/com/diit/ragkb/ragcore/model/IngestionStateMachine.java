package com.diit.ragkb.ragcore.model;

import java.util.EnumMap;
import java.util.EnumSet;
import java.util.Map;

/** 文档入库状态迁移规则，Worker 与管理接口均应通过此类校验状态变化。 */
public final class IngestionStateMachine {

    private static final Map<IngestionStatus, EnumSet<IngestionStatus>> TRANSITIONS = transitions();

    private IngestionStateMachine() {
    }

    public static boolean canTransition(IngestionStatus from, IngestionStatus to) {
        return from != null && to != null && TRANSITIONS.get(from).contains(to);
    }

    public static void requireTransition(IngestionStatus from, IngestionStatus to) {
        if (!canTransition(from, to)) {
            throw new IllegalArgumentException("不允许的入库状态迁移: " + from + " -> " + to);
        }
    }

    private static Map<IngestionStatus, EnumSet<IngestionStatus>> transitions() {
        Map<IngestionStatus, EnumSet<IngestionStatus>> transitions = new EnumMap<>(IngestionStatus.class);
        transitions.put(IngestionStatus.QUEUED, EnumSet.of(IngestionStatus.PARSING, IngestionStatus.FAILED, IngestionStatus.DELETING));
        transitions.put(IngestionStatus.PARSING, EnumSet.of(IngestionStatus.CHUNKING, IngestionStatus.FAILED, IngestionStatus.DELETING));
        transitions.put(IngestionStatus.CHUNKING, EnumSet.of(IngestionStatus.EMBEDDING, IngestionStatus.FAILED, IngestionStatus.DELETING));
        transitions.put(IngestionStatus.EMBEDDING, EnumSet.of(IngestionStatus.INDEXING, IngestionStatus.FAILED, IngestionStatus.DELETING));
        transitions.put(IngestionStatus.INDEXING, EnumSet.of(IngestionStatus.READY, IngestionStatus.FAILED, IngestionStatus.DELETING));
        transitions.put(IngestionStatus.READY, EnumSet.of(IngestionStatus.QUEUED, IngestionStatus.DELETING));
        transitions.put(IngestionStatus.FAILED, EnumSet.of(IngestionStatus.QUEUED, IngestionStatus.DELETING));
        transitions.put(IngestionStatus.DELETING, EnumSet.noneOf(IngestionStatus.class));
        return Map.copyOf(transitions);
    }
}
