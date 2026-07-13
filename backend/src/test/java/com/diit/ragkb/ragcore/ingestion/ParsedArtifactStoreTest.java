package com.diit.ragkb.ragcore.ingestion;

import com.diit.ragkb.ragcore.model.DocumentSection;
import com.diit.ragkb.ragcore.model.ParsedDocument;
import com.diit.ragkb.ragcore.storage.ObjectStorage;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

import static org.junit.jupiter.api.Assertions.*;

class ParsedArtifactStoreTest {

    private final MemoryObjectStorage storage = new MemoryObjectStorage();
    private final ParsedArtifactStore store = new ParsedArtifactStore(
            storage, new ObjectMapper().registerModule(new JavaTimeModule()));

    @Test
    void savesAndLoadsVersionedArtifact() throws Exception {
        IngestionTask initial = task(null, null);
        ParsedDocument parsed = parsed(initial.documentId());

        ParsedArtifactStore.SavedArtifact saved = store.save(initial, parsed);
        assertEquals("source/test.pdf.parsed-v1.json", saved.path());
        assertEquals("gateway-ocr", saved.parserName());
        assertEquals(ParsedArtifactStore.CURRENT_VERSION, saved.parserVersion());

        IngestionTask retry = task(saved.path(), saved.parserVersion());
        ParsedDocument loaded = store.load(retry).orElseThrow();
        assertEquals(parsed, loaded);
        assertEquals(1, storage.putCount);
    }

    @Test
    void ignoresOldVersionAndCorruptArtifact() {
        IngestionTask oldVersion = task("source/test.pdf.parsed-v0.json", "0");
        assertTrue(store.load(oldVersion).isEmpty());

        String corruptPath = "source/test.pdf.parsed-v1.json";
        storage.objects.put(corruptPath, "not-json".getBytes());
        assertTrue(store.load(task(corruptPath, ParsedArtifactStore.CURRENT_VERSION)).isEmpty());
    }

    private IngestionTask task(String artifactPath, String version) {
        UUID documentId = UUID.fromString("11111111-1111-1111-1111-111111111111");
        return new IngestionTask(
                UUID.fromString("22222222-2222-2222-2222-222222222222"), documentId,
                UUID.fromString("33333333-3333-3333-3333-333333333333"),
                UUID.fromString("44444444-4444-4444-4444-444444444444"),
                "test.pdf", "application/pdf", "source/test.pdf", artifactPath, version);
    }

    private ParsedDocument parsed(UUID documentId) {
        return new ParsedDocument(documentId, "application/pdf", "source/test.pdf",
                List.of(new DocumentSection("生产验收", List.of("第一章"), 1, null, null,
                        Map.of("ocr", "true"))),
                Map.of("parser", "gateway-ocr"));
    }

    static class MemoryObjectStorage implements ObjectStorage {
        private final Map<String, byte[]> objects = new ConcurrentHashMap<>();
        private int putCount;

        @Override
        public void put(String objectKey, InputStream input, long sizeBytes, String contentType) throws IOException {
            byte[] value = input.readAllBytes();
            if (value.length != sizeBytes) throw new IOException("size mismatch");
            objects.put(objectKey, value);
            putCount++;
        }

        @Override
        public InputStream open(String objectKey) throws IOException {
            byte[] value = objects.get(objectKey);
            if (value == null) throw new IOException("not found");
            return new ByteArrayInputStream(value);
        }

        @Override
        public void delete(String objectKey) {
            objects.remove(objectKey);
        }
    }
}
