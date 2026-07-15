package com.diit.ragkb.ragcore.generation;

/**
 * 非流式的单轮 Chat Completion 端口，供指代消解/摘要压缩/画像提炼这类"一次性、要完整结果"
 * 的辅助 LLM 调用复用，与面向用户的流式 {@link AnswerGenerator} 分开。
 */
public interface ChatCompletionClient {

    String complete(String systemPrompt, String userPrompt);
}
