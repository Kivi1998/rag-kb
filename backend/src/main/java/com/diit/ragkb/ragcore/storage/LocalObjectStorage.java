package com.diit.ragkb.ragcore.storage;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;

/** 本地开发/测试对象存储实现；生产环境应配置 rag.storage.type=minio。 */
@Component
@ConditionalOnProperty(prefix = "rag.storage", name = "type", havingValue = "local", matchIfMissing = true)
public class LocalObjectStorage implements ObjectStorage {

    private final Path root;

    public LocalObjectStorage(@Value("${rag.storage.local-root:./data/rag-objects}") String localRoot) {
        this.root = Path.of(localRoot).toAbsolutePath().normalize();
    }

    @Override
    public void put(String objectKey, InputStream input, long sizeBytes, String contentType) throws IOException {
        Path target = resolve(objectKey);
        Files.createDirectories(target.getParent());
        Files.copy(input, target, StandardCopyOption.REPLACE_EXISTING);
    }

    @Override
    public void delete(String objectKey) throws IOException {
        Files.deleteIfExists(resolve(objectKey));
    }

    private Path resolve(String objectKey) {
        Path target = root.resolve(objectKey).normalize();
        if (!target.startsWith(root)) {
            throw new IllegalArgumentException("非法对象存储路径");
        }
        return target;
    }
}
