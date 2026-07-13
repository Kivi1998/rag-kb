package com.diit.ragkb.ragcore.upload;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.util.Locale;
import java.util.Set;

/** 所有上传入口共享的文件名、扩展名和大小策略。 */
@Component
public class DocumentUploadPolicy {

    private static final int MAX_FILE_NAME_LENGTH = 500;
    private static final Set<String> ALLOWED_EXTENSIONS = Set.of(
            "md", "markdown", "txt", "pdf", "docx", "pptx", "srt", "vtt", "json", "yaml", "yml", "xml",
            "png", "jpg", "jpeg", "tif", "tiff", "mp3", "wav", "mp4", "mov", "mkv",
            "java", "py", "js", "ts", "tsx", "jsx", "go", "rs", "sql", "sh", "bash",
            "properties", "conf", "ini", "gradle", "pom");

    private final long maxSizeBytes;

    public DocumentUploadPolicy(@Value("${rag.upload.max-size-bytes:536870912}") long maxSizeBytes) {
        if (maxSizeBytes <= 0) throw new IllegalArgumentException("rag.upload.max-size-bytes 必须大于 0");
        this.maxSizeBytes = maxSizeBytes;
    }

    public ValidatedUpload validate(String originalFilename, long sizeBytes) {
        if (sizeBytes <= 0) throw new IllegalArgumentException("请选择非空文件");
        if (sizeBytes > maxSizeBytes) throw new IllegalArgumentException("文件大小超过上传策略限制");
        if (originalFilename == null || originalFilename.isBlank()) throw new IllegalArgumentException("文件名不能为空");
        String safeFileName = originalFilename.replace('\\', '/');
        safeFileName = safeFileName.substring(safeFileName.lastIndexOf('/') + 1).trim();
        if (safeFileName.isBlank() || safeFileName.length() > MAX_FILE_NAME_LENGTH || safeFileName.contains("\u0000")) {
            throw new IllegalArgumentException("文件名不合法");
        }
        int dot = safeFileName.lastIndexOf('.');
        if (dot <= 0 || dot == safeFileName.length() - 1) {
            throw new IllegalArgumentException("文件必须带有受支持的扩展名");
        }
        String extension = safeFileName.substring(dot + 1).toLowerCase(Locale.ROOT);
        if (!ALLOWED_EXTENSIONS.contains(extension)) throw new IllegalArgumentException("不支持的文件类型: " + extension);
        return new ValidatedUpload(safeFileName, extension, expectedContentType(extension), sizeBytes);
    }

    private String expectedContentType(String extension) {
        return switch (extension) {
            case "pdf" -> "application/pdf";
            case "docx" -> "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
            case "pptx" -> "application/vnd.openxmlformats-officedocument.presentationml.presentation";
            case "md", "markdown" -> "text/markdown";
            case "json" -> "application/json";
            case "yaml", "yml" -> "application/x-yaml";
            case "xml" -> "application/xml";
            case "srt" -> "application/x-subrip";
            case "vtt" -> "text/vtt";
            case "png" -> "image/png";
            case "jpg", "jpeg" -> "image/jpeg";
            case "tif", "tiff" -> "image/tiff";
            case "mp3" -> "audio/mpeg";
            case "wav" -> "audio/wav";
            case "mp4" -> "video/mp4";
            case "mov" -> "video/quicktime";
            case "mkv" -> "video/x-matroska";
            default -> "text/plain";
        };
    }

    public record ValidatedUpload(String safeFileName, String extension, String contentType, long sizeBytes) { }
}
