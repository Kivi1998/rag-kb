package com.diit.ragkb.ragcore.upload;

import java.util.Locale;

/**
 * 上传文件的轻量内容嗅探。它不依赖客户端 MIME，先拒绝与扩展名明显不符的二进制伪装文件。
 * 深层格式校验仍由对应 Parser 负责，避免在 HTTP 请求内执行高成本 Office/PDF 解析。
 */
public final class UploadContentInspector {

    private UploadContentInspector() {
    }

    public static String inspect(String filename, byte[] prefix) {
        String extension = extensionOf(filename);
        if (extension.equals("pdf")) {
            require(startsWith(prefix, "%PDF-".getBytes()), "PDF 文件头无效");
            return "application/pdf";
        }
        if (extension.equals("docx")) {
            require(isZip(prefix), "DOCX 必须是有效的 OOXML ZIP 文件");
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
        }
        if (extension.equals("pptx")) {
            require(isZip(prefix), "PPTX 必须是有效的 OOXML ZIP 文件");
            return "application/vnd.openxmlformats-officedocument.presentationml.presentation";
        }
        if (extension.equals("png")) {
            require(startsWith(prefix, new byte[]{(byte) 0x89, 'P', 'N', 'G'}), "PNG 文件头无效");
            return "image/png";
        }
        if (extension.equals("jpg") || extension.equals("jpeg")) {
            require(startsWith(prefix, new byte[]{(byte) 0xff, (byte) 0xd8, (byte) 0xff}), "JPEG 文件头无效");
            return "image/jpeg";
        }
        if (extension.equals("tif") || extension.equals("tiff")) {
            boolean littleEndian = startsWith(prefix, new byte[]{'I', 'I', 42, 0});
            boolean bigEndian = startsWith(prefix, new byte[]{'M', 'M', 0, 42});
            require(littleEndian || bigEndian, "TIFF 文件头无效");
            return "image/tiff";
        }
        if (extension.equals("wav")) {
            require(prefix.length >= 12 && startsWith(prefix, "RIFF".getBytes())
                    && prefix[8] == 'W' && prefix[9] == 'A' && prefix[10] == 'V' && prefix[11] == 'E', "WAV 文件头无效");
            return "audio/wav";
        }
        if (extension.equals("mp3")) {
            boolean id3 = startsWith(prefix, "ID3".getBytes());
            boolean frame = prefix.length >= 2 && (prefix[0] & 0xff) == 0xff && ((prefix[1] & 0xe0) == 0xe0);
            require(id3 || frame, "MP3 文件头无效");
            return "audio/mpeg";
        }
        if (extension.equals("mp4") || extension.equals("mov")) {
            require(prefix.length >= 12 && prefix[4] == 'f' && prefix[5] == 't' && prefix[6] == 'y' && prefix[7] == 'p',
                    "MP4/MOV 文件头无效");
            return extension.equals("mov") ? "video/quicktime" : "video/mp4";
        }
        if (extension.equals("mkv")) {
            require(startsWith(prefix, new byte[]{0x1a, 0x45, (byte) 0xdf, (byte) 0xa3}), "MKV 文件头无效");
            return "video/x-matroska";
        }
        if (isTextual(extension)) {
            require(!containsNul(prefix), "文本或代码文件包含二进制空字节");
            return switch (extension) {
                case "md", "markdown" -> "text/markdown";
                case "json" -> "application/json";
                case "yaml", "yml" -> "application/x-yaml";
                case "xml" -> "application/xml";
                case "srt" -> "application/x-subrip";
                case "vtt" -> "text/vtt";
                default -> "text/plain";
            };
        }
        throw new IllegalArgumentException("不支持的文件类型: " + extension);
    }

    private static boolean isTextual(String extension) {
        return switch (extension) {
            case "md", "markdown", "txt", "srt", "vtt", "json", "yaml", "yml", "xml",
                    "java", "py", "js", "ts", "tsx", "jsx", "go", "rs", "sql", "sh", "bash",
                    "properties", "conf", "ini", "gradle", "pom" -> true;
            default -> false;
        };
    }

    private static String extensionOf(String filename) {
        int dot = filename == null ? -1 : filename.lastIndexOf('.');
        return dot < 0 ? "" : filename.substring(dot + 1).toLowerCase(Locale.ROOT);
    }

    private static boolean isZip(byte[] value) {
        return value.length >= 4 && value[0] == 'P' && value[1] == 'K'
                && ((value[2] == 3 && value[3] == 4) || (value[2] == 5 && value[3] == 6));
    }

    private static boolean startsWith(byte[] value, byte[] expected) {
        if (value.length < expected.length) return false;
        for (int i = 0; i < expected.length; i++) {
            if (value[i] != expected[i]) return false;
        }
        return true;
    }

    private static boolean containsNul(byte[] value) {
        for (byte b : value) {
            if (b == 0) return true;
        }
        return false;
    }

    private static void require(boolean condition, String message) {
        if (!condition) throw new IllegalArgumentException(message);
    }
}
