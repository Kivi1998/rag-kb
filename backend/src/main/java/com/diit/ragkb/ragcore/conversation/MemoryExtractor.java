package com.diit.ragkb.ragcore.conversation;

import java.util.UUID;

/**
 * 从一轮问答中异步提炼候选画像条目（偏好/事实/长期目标），语义去重后写入长期记忆。
 * 实现 SHALL 捕获内部所有异常，不得向调用方抛出——这是锦上添花的增强，失败不应影响
 * 用户已经收到的回答。
 */
public interface MemoryExtractor {

    void extractAndStore(UUID organizationId, UUID memberId, UUID sessionId, String question, String answer);
}
