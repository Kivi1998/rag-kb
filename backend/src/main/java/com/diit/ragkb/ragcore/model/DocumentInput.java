package com.diit.ragkb.ragcore.model;

import java.io.IOException;
import java.io.InputStream;
import java.util.UUID;

/**
 * 待解析文档的抽象输入。
 *
 * <p>解析器只依赖此接口，调用方可以将其实现为 MinIO、文件系统或测试内存数据，避免核心层绑定存储实现。</p>
 */
public interface DocumentInput {

    UUID documentId();

    String filename();

    String contentType();

    String sourcePath();

    InputStream openStream() throws IOException;
}
