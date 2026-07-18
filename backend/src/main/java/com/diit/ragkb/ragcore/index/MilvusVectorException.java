package com.diit.ragkb.ragcore.index;

/** Milvus Collection、写入或检索契约违反时的统一异常。 */
public class MilvusVectorException extends RuntimeException {
    public MilvusVectorException(String message) {
        super(message);
    }

    public MilvusVectorException(String message, Throwable cause) {
        super(message, cause);
    }
}
