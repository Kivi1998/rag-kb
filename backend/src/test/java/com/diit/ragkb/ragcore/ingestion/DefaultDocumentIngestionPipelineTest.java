package com.diit.ragkb.ragcore.ingestion;

import com.diit.ragkb.ragcore.chunk.Chunker;
import com.diit.ragkb.ragcore.embedding.EmbeddingClient;
import com.diit.ragkb.ragcore.index.ChunkIndex;
import com.diit.ragkb.ragcore.model.Chunk;
import com.diit.ragkb.ragcore.model.DocumentSection;
import com.diit.ragkb.ragcore.model.EmbeddingResult;
import com.diit.ragkb.ragcore.model.IngestionStatus;
import com.diit.ragkb.ragcore.model.ParsedDocument;
import com.diit.ragkb.ragcore.parser.DocumentParser;
import com.diit.ragkb.ragcore.parser.impl.DocumentParserFactory;
import com.diit.ragkb.ragcore.storage.ObjectStorage;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

/** 验证 T107 的阶段顺序，防止无索引写入时被标记 READY。 */
class DefaultDocumentIngestionPipelineTest {

    @Test
    void pipeline_runsParseChunkEmbedIndexThenReady() throws Exception {
        UUID orgId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID documentId = UUID.randomUUID();
        IngestionTask task = new IngestionTask(UUID.randomUUID(), documentId, orgId, kbId,
                "guide.md", "text/markdown", "org/x/kb/y/doc.md");

        DocumentParser parser = new DocumentParser() {
            @Override public boolean supports(String contentType, String filename) { return true; }
            @Override public ParsedDocument parse(com.diit.ragkb.ragcore.model.DocumentInput input) {
                return new ParsedDocument(input.documentId(), input.contentType(), input.sourcePath(),
                        List.of(new DocumentSection("正文", List.of("标题"), null, 1, 1, Map.of())), Map.of());
            }
        };
        DocumentParserFactory parserFactory = new DocumentParserFactory(List.of(parser));
        Chunk chunk = new Chunk("chunk-1", orgId, kbId, documentId, 0, "正文", List.of("标题"),
                task.objectStoragePath(), null, 1, 1, "markdown", "hash", Map.of());
        Chunker chunker = (parsed, context, options) -> List.of(chunk);
        EmbeddingClient embedding = texts -> new EmbeddingResult("embedding-v1", List.of(List.of(0.1f, 0.2f)));
        ChunkIndex index = mock(ChunkIndex.class);
        ObjectStorage storage = new ObjectStorage() {
            @Override public void put(String key, InputStream input, long size, String contentType) { }
            @Override public InputStream open(String key) { return new ByteArrayInputStream("正文".getBytes(StandardCharsets.UTF_8)); }
            @Override public void delete(String key) { }
        };
        IngestionJobLifecycleService lifecycle = mock(IngestionJobLifecycleService.class);

        new DefaultDocumentIngestionPipeline(parserFactory, chunker, embedding, index, storage, lifecycle).process(task);

        verify(lifecycle).advance(task.jobId(), IngestionStatus.CHUNKING);
        verify(lifecycle).advance(task.jobId(), IngestionStatus.EMBEDDING);
        verify(lifecycle).advance(task.jobId(), IngestionStatus.INDEXING);
        verify(index).upsert(eq(List.of(chunk)), eq(List.of(List.of(0.1f, 0.2f))), eq("embedding-v1"));
        verify(lifecycle).advance(task.jobId(), IngestionStatus.READY);
    }
}
