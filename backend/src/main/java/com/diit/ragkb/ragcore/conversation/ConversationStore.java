package com.diit.ragkb.ragcore.conversation;

import java.util.List;
import java.util.UUID;

/**
 * 会话消息的读写抽象：写直达（Redis 热路径滑动窗口 + MongoDB 长期存档同步写入，两者都成功才算完成）。
 *
 * <p>Redis 不可达时，读操作 SHALL 优雅降级（fail-open，退化为无历史单轮问答），不得抛异常中断问答流程；
 * 这与 JWT 黑名单场景的 fail-close 语义不同，实现时不应混用同一套异常处理策略。</p>
 */
public interface ConversationStore {

    /** 写直达：同步写入 Redis 滑动窗口与 MongoDB 长期存档。 */
    void appendMessage(UUID organizationId, UUID kbId, UUID memberId, UUID sessionId, ChatMessage message);

    /**
     * 取该会话最近的原始消息（按时间升序）。Redis 不可达时返回空列表并记录 warning，
     * 不抛异常——调用方应把这种情况当作"暂时没有短期记忆"处理，而不是请求失败。
     */
    List<ChatMessage> recentRawMessages(UUID organizationId, UUID sessionId);

    /** MongoDB 长期存档查询（供 `GET .../sessions/{sessionId}/messages` 接口使用）。 */
    List<ChatMessage> archivedMessages(UUID organizationId, UUID sessionId);
}
