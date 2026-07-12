package com.diit.ragkb.ragcore.model;

/** 模型服务不可用、超时或协议不兼容时抛出的可识别异常。 */
public class ModelClientException extends RuntimeException {

    public ModelClientException(String message) {
        super(message);
    }

    public ModelClientException(String message, Throwable cause) {
        super(message, cause);
    }
}
