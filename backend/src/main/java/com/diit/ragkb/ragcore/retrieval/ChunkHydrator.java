package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.ragcore.model.Chunk;

import java.util.List;
import java.util.UUID;

/** 按向量命中 ID 补齐 ES Chunk；返回值顺序必须与可找到的输入 ID 顺序一致。 */
public interface ChunkHydrator {
    List<Chunk> findByChunkIds(UUID organizationId, UUID knowledgeBaseId, List<String> chunkIds);
}
