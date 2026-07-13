package com.diit.ragkb.ragcore.ingestion;

import com.diit.ragkb.ragcore.model.ParsedDocument;
import com.diit.ragkb.ragcore.storage.ObjectStorage;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Optional;

/** 解析结果对象存储，避免后续阶段重试时重复执行高成本 OCR/ASR。 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ParsedArtifactStore {

    public static final String CURRENT_VERSION = "1";

    private final ObjectStorage objectStorage;
    private final ObjectMapper objectMapper;

    public Optional<ParsedDocument> load(IngestionTask task) {
        if (task.parseArtifactPath() == null || task.parseArtifactPath().isBlank()
                || !CURRENT_VERSION.equals(task.parserVersion())) {
            return Optional.empty();
        }
        try (InputStream input = objectStorage.open(task.parseArtifactPath())) {
            return Optional.of(objectMapper.readValue(input, ParsedDocument.class));
        } catch (IOException ex) {
            log.warn("解析产物读取失败，将重新解析，documentId={}, artifact={}",
                    task.documentId(), task.parseArtifactPath(), ex);
            return Optional.empty();
        }
    }

    public SavedArtifact save(IngestionTask task, ParsedDocument parsed) throws IOException {
        String artifactPath = task.objectStoragePath() + ".parsed-v" + CURRENT_VERSION + ".json";
        Path temp = Files.createTempFile("rag-parsed-", ".json");
        try {
            objectMapper.writeValue(temp.toFile(), parsed);
            long size = Files.size(temp);
            try (InputStream input = Files.newInputStream(temp)) {
                objectStorage.put(artifactPath, input, size, "application/json");
            }
        } finally {
            Files.deleteIfExists(temp);
        }
        String parserName = parsed.metadata().getOrDefault("parser", "local-java-parser");
        return new SavedArtifact(artifactPath, parserName, CURRENT_VERSION);
    }

    public record SavedArtifact(String path, String parserName, String parserVersion) { }
}
