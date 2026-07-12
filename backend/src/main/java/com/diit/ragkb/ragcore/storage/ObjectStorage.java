package com.diit.ragkb.ragcore.storage;

import java.io.IOException;
import java.io.InputStream;

/** 原始文档对象存储端口，支持本地开发与 MinIO/S3 生产实现。 */
public interface ObjectStorage {

    void put(String objectKey, InputStream input, long sizeBytes, String contentType) throws IOException;

    /** 打开已保存的对象；调用方负责关闭返回的流。 */
    InputStream open(String objectKey) throws IOException;

    void delete(String objectKey) throws IOException;
}
