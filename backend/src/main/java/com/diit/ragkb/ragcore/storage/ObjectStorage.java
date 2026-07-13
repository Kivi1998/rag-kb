package com.diit.ragkb.ragcore.storage;

import java.io.IOException;
import java.io.InputStream;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;

/** 原始文档对象存储端口，支持本地开发与 MinIO/S3 生产实现。 */
public interface ObjectStorage {

    void put(String objectKey, InputStream input, long sizeBytes, String contentType) throws IOException;

    /** 打开已保存的对象；调用方负责关闭返回的流。 */
    InputStream open(String objectKey) throws IOException;

    void delete(String objectKey) throws IOException;

    /** 是否支持浏览器/客户端直接上传；本地文件系统实现默认不支持。 */
    default boolean supportsDirectUpload() {
        return false;
    }

    /** 为单个对象签发短期 PUT 地址。 */
    default PresignedUpload presignPut(String objectKey, String contentType, Duration ttl) throws IOException {
        throw new UnsupportedOperationException("当前对象存储不支持预签名直传");
    }

    /** 查询已上传对象的服务端元数据，用于完成回调校验。 */
    default StoredObject stat(String objectKey) throws IOException {
        throw new UnsupportedOperationException("当前对象存储不支持对象元数据查询");
    }

    record PresignedUpload(String url, String method, Map<String, String> headers, Instant expiresAt) {
        public PresignedUpload {
            headers = headers == null ? Map.of() : Map.copyOf(headers);
        }
    }

    record StoredObject(long sizeBytes, String contentType, String etag) { }
}
