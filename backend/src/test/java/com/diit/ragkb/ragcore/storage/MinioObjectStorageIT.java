package com.diit.ragkb.ragcore.storage;

import io.minio.BucketExistsArgs;
import io.minio.MakeBucketArgs;
import io.minio.MinioClient;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.UUID;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.Executors;

import static org.junit.jupiter.api.Assertions.*;

/** 真实 MinIO 联调；默认跳过，配置 RAG_MINIO_TEST_ENDPOINT 后显式运行。 */
class MinioObjectStorageIT {

    @Test
    @DisplayName("预签名 PUT 后可查询、读取并删除真实 MinIO 对象")
    void presignedUploadLifecycle() throws Exception {
        String endpoint = System.getenv("RAG_MINIO_TEST_ENDPOINT");
        Assumptions.assumeTrue(endpoint != null && !endpoint.isBlank(), "未配置真实 MinIO");
        String accessKey = System.getenv().getOrDefault("RAG_MINIO_TEST_ACCESS_KEY", "ragadmin");
        String secretKey = System.getenv().getOrDefault("RAG_MINIO_TEST_SECRET_KEY", "ragadmin123");
        String bucket = System.getenv().getOrDefault("RAG_MINIO_TEST_BUCKET", "rag-kb-test");
        MinioClient client = MinioClient.builder().endpoint(endpoint).credentials(accessKey, secretKey).build();
        if (!client.bucketExists(BucketExistsArgs.builder().bucket(bucket).build())) {
            client.makeBucket(MakeBucketArgs.builder().bucket(bucket).build());
        }

        MinioObjectStorage storage = new MinioObjectStorage(endpoint, accessKey, secretKey, bucket);
        String key = "acceptance/" + UUID.randomUUID() + ".txt";
        byte[] content = "production minio acceptance".getBytes(java.nio.charset.StandardCharsets.UTF_8);
        ObjectStorage.PresignedUpload signed = storage.presignPut(key, "text/plain", Duration.ofMinutes(5));

        HttpRequest request = HttpRequest.newBuilder(URI.create(signed.url()))
                .header("Content-Type", "text/plain")
                .PUT(HttpRequest.BodyPublishers.ofByteArray(content))
                .build();
        HttpResponse<String> response = HttpClient.newHttpClient().send(request, HttpResponse.BodyHandlers.ofString());
        assertTrue(response.statusCode() >= 200 && response.statusCode() < 300, response.body());
        assertEquals(content.length, storage.stat(key).sizeBytes());
        try (var input = storage.open(key)) {
            assertArrayEquals(content, input.readAllBytes());
        }
        storage.delete(key);
        assertThrows(java.io.IOException.class, () -> storage.stat(key));
    }

    @Test
    @DisplayName("批量预签名上传可完成声明数量的真实对象生命周期")
    void presignedUploadCapacity() throws Exception {
        int count = Integer.parseInt(System.getenv().getOrDefault("RAG_MINIO_LOAD_TEST_COUNT", "0"));
        Assumptions.assumeTrue(count > 0, "未启用 MinIO 容量测试");
        String endpoint = requiredEndpoint();
        String accessKey = System.getenv().getOrDefault("RAG_MINIO_TEST_ACCESS_KEY", "ragadmin");
        String secretKey = System.getenv().getOrDefault("RAG_MINIO_TEST_SECRET_KEY", "ragadmin123");
        String bucket = System.getenv().getOrDefault("RAG_MINIO_TEST_BUCKET", "rag-kb-test");
        ensureBucket(endpoint, accessKey, secretKey, bucket);

        MinioObjectStorage storage = new MinioObjectStorage(endpoint, accessKey, secretKey, bucket);
        HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build();
        byte[] content = new byte[4096];
        int concurrency = Math.min(16, Math.max(1, Integer.parseInt(
                System.getenv().getOrDefault("RAG_MINIO_LOAD_TEST_CONCURRENCY", "8"))));
        var executor = Executors.newFixedThreadPool(concurrency);
        var completion = new java.util.concurrent.ExecutorCompletionService<Long>(executor);
        long wallStart = System.nanoTime();
        try {
            for (int i = 0; i < count; i++) {
                int index = i;
                completion.submit(() -> uploadAndDelete(storage, http, content, index));
            }
            List<Long> latencyMs = new ArrayList<>(count);
            for (int i = 0; i < count; i++) latencyMs.add(completion.take().get());
            Collections.sort(latencyMs);
            double elapsedSeconds = (System.nanoTime() - wallStart) / 1_000_000_000.0;
            System.out.printf(java.util.Locale.ROOT,
                    "MinIO capacity: total=%d success=%d concurrency=%d elapsed=%.3fs rps=%.3f p95=%dms p99=%dms%n",
                    count, latencyMs.size(), concurrency, elapsedSeconds, count / elapsedSeconds,
                    latencyMs.get((int) ((count - 1) * 0.95)), latencyMs.get((int) ((count - 1) * 0.99)));
            assertEquals(count, latencyMs.size());
        } finally {
            executor.shutdownNow();
        }
    }

    private long uploadAndDelete(MinioObjectStorage storage, HttpClient http, byte[] content, int index)
            throws Exception {
        long started = System.nanoTime();
        String key = "capacity/" + index + "-" + UUID.randomUUID() + ".bin";
        ObjectStorage.PresignedUpload signed = storage.presignPut(key, "application/octet-stream", Duration.ofMinutes(10));
        HttpResponse<String> response = http.send(HttpRequest.newBuilder(URI.create(signed.url()))
                .header("Content-Type", "application/octet-stream")
                .PUT(HttpRequest.BodyPublishers.ofByteArray(content)).build(), HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new AssertionError("MinIO PUT failed: " + response.statusCode() + " " + response.body());
        }
        assertEquals(content.length, storage.stat(key).sizeBytes());
        storage.delete(key);
        return (System.nanoTime() - started) / 1_000_000;
    }

    private String requiredEndpoint() {
        String endpoint = System.getenv("RAG_MINIO_TEST_ENDPOINT");
        Assumptions.assumeTrue(endpoint != null && !endpoint.isBlank(), "未配置真实 MinIO");
        return endpoint;
    }

    private void ensureBucket(String endpoint, String accessKey, String secretKey, String bucket) throws Exception {
        MinioClient client = MinioClient.builder().endpoint(endpoint).credentials(accessKey, secretKey).build();
        if (!client.bucketExists(BucketExistsArgs.builder().bucket(bucket).build())) {
            client.makeBucket(MakeBucketArgs.builder().bucket(bucket).build());
        }
    }
}
