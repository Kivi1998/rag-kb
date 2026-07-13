package com.diit.ragkb.ragcore.ingestion;

import com.diit.ragkb.ragcore.chunk.Chunker;
import com.diit.ragkb.ragcore.chunk.ChunkingContext;
import com.diit.ragkb.ragcore.chunk.ChunkingOptions;
import com.diit.ragkb.ragcore.embedding.EmbeddingClient;
import com.diit.ragkb.ragcore.index.ChunkIndex;
import com.diit.ragkb.ragcore.model.DocumentInput;
import com.diit.ragkb.ragcore.model.EmbeddingResult;
import com.diit.ragkb.ragcore.model.IngestionStatus;
import com.diit.ragkb.ragcore.model.ParsedDocument;
import com.diit.ragkb.ragcore.parser.impl.DocumentParserFactory;
import com.diit.ragkb.ragcore.storage.ObjectStorage;
import lombok.RequiredArgsConstructor;

import java.io.IOException;
import java.io.InputStream;
import java.util.List;

/** Parser → Chunker → Embedding → ES 的生产摄取编排。 */
@RequiredArgsConstructor
public class DefaultDocumentIngestionPipeline implements DocumentIngestionPipeline {

    private final DocumentParserFactory parserFactory;
    private final Chunker chunker;
    private final EmbeddingClient embeddingClient;
    private final ChunkIndex chunkIndex;
    private final ObjectStorage objectStorage;
    private final IngestionJobLifecycleService lifecycleService;
    private final ParsedArtifactStore artifactStore;
    private final IngestionMetrics metrics;

    @Override
    public void process(IngestionTask task) throws Exception {
        requireStoragePath(task);
        ParsedDocument parsed = timed("parse", () -> loadOrParse(task));
        lifecycleService.advance(task.jobId(), IngestionStatus.CHUNKING);

        var chunks = timed("chunk", () -> chunker.chunk(parsed,
                new ChunkingContext(task.organizationId(), task.knowledgeBaseId()), ChunkingOptions.defaults()));
        if (chunks.isEmpty()) {
            throw new IllegalArgumentException("文档不含可索引的文本内容");
        }
        lifecycleService.advance(task.jobId(), IngestionStatus.EMBEDDING);

        EmbeddingResult embedding = timed("embedding",
                () -> embeddingClient.embed(chunks.stream().map(chunk -> chunk.content()).toList()));
        List<List<Float>> vectors = embedding.vectors();
        if (vectors.size() != chunks.size()) {
            throw new IllegalStateException("Embedding 返回向量数量与 chunk 数量不一致");
        }
        lifecycleService.advance(task.jobId(), IngestionStatus.INDEXING);

        timed("index", () -> {
            chunkIndex.upsert(chunks, vectors, embedding.modelVersion());
            return null;
        });
        lifecycleService.advance(task.jobId(), IngestionStatus.READY);
    }

    private ParsedDocument loadOrParse(IngestionTask task) throws Exception {
        ParsedDocument parsed = artifactStore.load(task).orElse(null);
        if (parsed != null) return parsed;
        parsed = parserFactory.parse(new StoredDocumentInput(task, objectStorage));
        ParsedArtifactStore.SavedArtifact saved = artifactStore.save(task, parsed);
        lifecycleService.recordParsedArtifact(task.jobId(), saved.path(), saved.parserName(), saved.parserVersion());
        return parsed;
    }

    private <T> T timed(String stage, ThrowingSupplier<T> action) throws Exception {
        long started = metrics.startNanos();
        try {
            T result = action.get();
            metrics.stageFinished(stage, started, true);
            return result;
        } catch (Exception ex) {
            metrics.stageFinished(stage, started, false);
            throw ex;
        }
    }

    private void requireStoragePath(IngestionTask task) {
        if (task.objectStoragePath() == null || task.objectStoragePath().isBlank()) {
            throw new IllegalStateException("文档缺少对象存储路径");
        }
    }

    private record StoredDocumentInput(IngestionTask task, ObjectStorage storage) implements DocumentInput {
        @Override public java.util.UUID documentId() { return task.documentId(); }
        @Override public String filename() { return task.filename(); }
        @Override public String contentType() { return task.contentType(); }
        @Override public String sourcePath() { return task.objectStoragePath(); }
        @Override public InputStream openStream() throws IOException { return storage.open(task.objectStoragePath()); }
    }

    @FunctionalInterface
    private interface ThrowingSupplier<T> {
        T get() throws Exception;
    }
}
