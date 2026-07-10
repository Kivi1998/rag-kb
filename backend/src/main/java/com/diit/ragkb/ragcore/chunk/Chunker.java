package com.diit.ragkb.ragcore.chunk;

import com.diit.ragkb.ragcore.model.Chunk;
import com.diit.ragkb.ragcore.model.ParsedDocument;

import java.util.List;

/** 将解析结果切为可检索的上下文块。 */
public interface Chunker {

    List<Chunk> chunk(ParsedDocument document, ChunkingContext context, ChunkingOptions options);
}
