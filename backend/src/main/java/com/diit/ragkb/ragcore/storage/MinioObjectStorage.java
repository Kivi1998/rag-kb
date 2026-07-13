package com.diit.ragkb.ragcore.storage;

import io.minio.MinioClient;
import io.minio.GetObjectArgs;
import io.minio.PutObjectArgs;
import io.minio.RemoveObjectArgs;
import io.minio.GetPresignedObjectUrlArgs;
import io.minio.StatObjectArgs;
import io.minio.StatObjectResponse;
import io.minio.http.Method;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.io.InputStream;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;

/** MinIO/S3 兼容对象存储实现。bucket 由部署前置创建并授予最小权限。 */
@Component
@ConditionalOnProperty(prefix = "rag.storage", name = "type", havingValue = "minio")
public class MinioObjectStorage implements ObjectStorage {

    private final MinioClient client;
    private final String bucket;

    public MinioObjectStorage(@Value("${rag.storage.endpoint}") String endpoint,
                              @Value("${rag.storage.access-key}") String accessKey,
                              @Value("${rag.storage.secret-key}") String secretKey,
                              @Value("${rag.storage.bucket}") String bucket) {
        if (endpoint == null || endpoint.isBlank() || accessKey == null || accessKey.isBlank()
                || secretKey == null || secretKey.isBlank()) {
            throw new IllegalStateException("MinIO 存储已启用但 endpoint/access-key/secret-key 未完整配置");
        }
        this.client = MinioClient.builder().endpoint(endpoint).credentials(accessKey, secretKey).build();
        this.bucket = bucket;
    }

    @Override
    public void put(String objectKey, InputStream input, long sizeBytes, String contentType) throws IOException {
        try {
            client.putObject(PutObjectArgs.builder().bucket(bucket).object(objectKey).stream(input, sizeBytes, -1)
                    .contentType(contentType).build());
        } catch (Exception e) {
            throw new IOException("MinIO 上传失败", e);
        }
    }

    @Override
    public InputStream open(String objectKey) throws IOException {
        try {
            return client.getObject(GetObjectArgs.builder().bucket(bucket).object(objectKey).build());
        } catch (Exception e) {
            throw new IOException("MinIO 读取失败", e);
        }
    }

    @Override
    public void delete(String objectKey) throws IOException {
        try {
            client.removeObject(RemoveObjectArgs.builder().bucket(bucket).object(objectKey).build());
        } catch (Exception e) {
            throw new IOException("MinIO 删除失败", e);
        }
    }

    @Override
    public boolean supportsDirectUpload() {
        return true;
    }

    @Override
    public PresignedUpload presignPut(String objectKey, String contentType, Duration ttl) throws IOException {
        int expirySeconds = Math.toIntExact(ttl.toSeconds());
        try {
            String url = client.getPresignedObjectUrl(GetPresignedObjectUrlArgs.builder()
                    .method(Method.PUT)
                    .bucket(bucket)
                    .object(objectKey)
                    .expiry(expirySeconds)
                    .build());
            return new PresignedUpload(url, "PUT", Map.of("Content-Type", contentType), Instant.now().plus(ttl));
        } catch (Exception e) {
            throw new IOException("MinIO 预签名上传地址生成失败", e);
        }
    }

    @Override
    public StoredObject stat(String objectKey) throws IOException {
        try {
            StatObjectResponse stat = client.statObject(StatObjectArgs.builder().bucket(bucket).object(objectKey).build());
            return new StoredObject(stat.size(), stat.contentType(), stat.etag());
        } catch (Exception e) {
            throw new IOException("MinIO 对象元数据查询失败", e);
        }
    }
}
