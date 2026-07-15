package com.diit.ragkb.ragcore.conversation;

import java.util.List;

/** 把超出 token 预算的最旧消息压缩成一段摘要（自研 prompt，不引入编排框架）。 */
public interface ConversationSummarizer {

    String summarize(List<ChatMessage> messagesToCompress);
}
