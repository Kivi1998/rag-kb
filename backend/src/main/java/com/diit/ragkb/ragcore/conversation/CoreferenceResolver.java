package com.diit.ragkb.ragcore.conversation;

import java.util.List;

/**
 * 检索前把用户问题里的代词/省略指代补全为独立完整的问题，仅解决指代消解，
 * 不得改写技术术语/错误码/配置项等专有名词。调用失败/超时应由实现负责降级（返回原始问题），
 * 不应向调用方抛出异常中断问答流程。
 */
public interface CoreferenceResolver {

    String resolve(String question, List<ChatMessage> history);
}
