package com.diit.ragkb.ragcore.quickdocument;

import java.util.List;
import java.util.UUID;

/** 会话内临时文档的存取，实现负责 TTL 与过期清理，调用方不感知底层存储细节。 */
public interface QuickDocumentStore {

    void save(QuickDocument document);

    /** 只返回未过期的文档；已过期的引用会被自愈清理，不需要调用方处理。 */
    List<QuickDocument> findAllBySession(UUID sessionId);

    void delete(UUID sessionId, UUID docId);

    /** 续期命中的文档（及其所属会话索引）的 TTL，未命中的文档不受影响，按原 TTL 自然过期。 */
    void touch(UUID sessionId, List<UUID> docIds);
}
