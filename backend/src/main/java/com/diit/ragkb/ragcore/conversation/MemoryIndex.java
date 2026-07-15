package com.diit.ragkb.ragcore.conversation;

import java.util.List;
import java.util.UUID;

/**
 * 统一语义记忆检索端口：短期会话内历史（{@code session_id} 过滤）与长期跨会话画像
 * （{@code member_id} 过滤）复用同一套向量检索实现，只是过滤条件不同。
 */
public interface MemoryIndex {

    /** 写入一条记忆（会话消息或画像条目），{@code vector} 与 chunk embedding 用同一模型/维度。 */
    void upsert(MemoryRecord record, List<Float> vector);

    /** 删除一条记忆（画像条目定期清理用）。 */
    void delete(String memoryId);

    /** 限定 sessionId 检索语义相关的历史会话消息，按相关度降序。 */
    List<ScoredMemoryRecord> searchSessionHistory(UUID organizationId, UUID sessionId, List<Float> queryVector,
                                                  int topK);

    /** 限定 memberId（不限 session）检索语义相关的长期画像条目，按相关度降序；分数用于新条目的语义去重判断。 */
    List<ScoredMemoryRecord> searchProfileItems(UUID organizationId, UUID memberId, List<Float> queryVector,
                                                int topK);

    /** 检索结果附带的 ES 相关度分数（kNN cosine 相似度场景下大致落在 0~1，用于去重阈值判断）。 */
    record ScoredMemoryRecord(MemoryRecord record, double score) {
    }
}
