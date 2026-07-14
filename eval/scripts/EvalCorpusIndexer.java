import com.diit.ragkb.ragcore.chunk.Chunker;
import com.diit.ragkb.ragcore.chunk.ChunkingContext;
import com.diit.ragkb.ragcore.chunk.ChunkingOptions;
import com.diit.ragkb.ragcore.chunk.impl.TechnicalChunker;
import com.diit.ragkb.ragcore.model.Chunk;
import com.diit.ragkb.ragcore.model.DocumentInput;
import com.diit.ragkb.ragcore.model.ParsedDocument;
import com.diit.ragkb.ragcore.parser.impl.DocumentParserFactory;

import java.io.BufferedInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 评测集 dump 工具 —— 读取 corpus 目录里的所有文档，
 * 用 V3 DocumentParserFactory 解析 + TechnicalChunker 切块，
 * 输出 JSONL 索引（每行一个 chunk），供人工标注 ground-truth 使用。
 *
 * 用法：
 *   java -cp $(cat /tmp/rag-cp.txt):backend/target/classes:eval/scripts \
 *        EvalCorpusIndexer <corpus-dir> <output.jsonl> [org-id] [kb-id]
 */
public class EvalCorpusIndexer {

    public static void main(String[] args) throws IOException {
        if (args.length < 2) {
            System.err.println("usage: java EvalCorpusIndexer <corpus-dir> <output.jsonl> [org-id] [kb-id]");
            System.exit(2);
        }

        Path corpusDir = Path.of(args[0]);
        Path output = Path.of(args[1]);
        UUID orgId = args.length > 2 ? UUID.fromString(args[2]) : UUID.fromString("00000000-0000-0000-0000-000000000001");
        UUID kbId  = args.length > 3 ? UUID.fromString(args[3]) : UUID.fromString("00000000-0000-0000-0000-000000000002");

        DocumentParserFactory parserFactory = DocumentParserFactory.createDefault();
        Chunker chunker = new TechnicalChunker();
        ChunkingOptions options = ChunkingOptions.defaults();
        ChunkingContext context = new ChunkingContext(orgId, kbId);

        int fileCount = 0;
        int chunkCount = 0;
        int skippedCount = 0;
        StringBuilder jsonl = new StringBuilder();

        try (var stream = Files.list(corpusDir)) {
            List<Path> files = stream.filter(Files::isRegularFile).sorted().toList();
            for (Path file : files) {
                String filename = file.getFileName().toString();
                String contentType = guessContentType(filename);
                UUID docId = UUID.nameUUIDFromBytes(filename.getBytes(StandardCharsets.UTF_8));

                try {
                    DocumentInput input = new FileDocumentInput(docId, filename, contentType, file);
                    ParsedDocument parsed = parserFactory.parse(input);
                    List<Chunk> chunks = chunker.chunk(parsed, context, options);

                    for (Chunk c : chunks) {
                        Map<String, Object> obj = new LinkedHashMap<>();
                        obj.put("chunk_id", c.id());
                        obj.put("document_id", c.documentId().toString());
                        obj.put("document_name", filename);
                        obj.put("ordinal", c.ordinal());
                        obj.put("heading_path", c.headingPath());
                        obj.put("page_no", c.pageNo());
                        obj.put("line_start", c.lineStart());
                        obj.put("line_end", c.lineEnd());
                        obj.put("language", c.language() == null ? "" : c.language());
                        obj.put("content_hash", c.contentHash());
                        obj.put("snippet", snippet(c.content()));
                        obj.put("content", c.content());
                        obj.put("metadata", c.metadata());
                        jsonl.append(toJson(obj)).append('\n');
                        chunkCount++;
                    }
                    fileCount++;
                    System.out.printf("[ok] %s -> %d chunks%n", filename, chunks.size());
                } catch (Exception ex) {
                    skippedCount++;
                    System.err.printf("[skip] %s : %s%n", filename, ex.getMessage());
                }
            }
        }

        Path parent = output.getParent();
        if (parent != null) Files.createDirectories(parent);
        Files.writeString(output, jsonl.toString(), StandardCharsets.UTF_8);

        System.out.println();
        System.out.println("=================================");
        System.out.printf("  files ok: %d, skipped: %d, chunks total: %d%n", fileCount, skippedCount, chunkCount);
        System.out.printf("  output: %s%n", output.toAbsolutePath());
        System.out.println("=================================");
    }

    private static String snippet(String content) {
        if (content == null) return "";
        String s = content.strip();
        return s.length() <= 200 ? s : s.substring(0, 200) + "...";
    }

    private static String guessContentType(String filename) {
        String lower = filename.toLowerCase();
        if (lower.endsWith(".md") || lower.endsWith(".markdown")) return "text/markdown";
        if (lower.endsWith(".docx")) return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
        if (lower.endsWith(".pdf")) return "application/pdf";
        if (lower.endsWith(".pptx")) return "application/vnd.openxmlformats-officedocument.presentationml.presentation";
        if (lower.endsWith(".txt")) return "text/plain";
        if (lower.endsWith(".json")) return "application/json";
        if (lower.endsWith(".xml")) return "application/xml";
        if (lower.endsWith(".yaml") || lower.endsWith(".yml")) return "application/x-yaml";
        if (lower.endsWith(".srt") || lower.endsWith(".vtt")) return "text/plain";
        return "application/octet-stream";
    }

    private static String toJson(Object obj) {
        if (obj == null) return "null";
        if (obj instanceof String) return jsonString((String) obj);
        if (obj instanceof Number || obj instanceof Boolean) return obj.toString();
        if (obj instanceof Map) {
            StringBuilder sb = new StringBuilder("{");
            boolean first = true;
            for (Map.Entry<?, ?> e : ((Map<?, ?>) obj).entrySet()) {
                if (!first) sb.append(',');
                first = false;
                sb.append(jsonString(String.valueOf(e.getKey()))).append(':').append(toJson(e.getValue()));
            }
            return sb.append('}').toString();
        }
        if (obj instanceof List) {
            StringBuilder sb = new StringBuilder("[");
            boolean first = true;
            for (Object e : (List<?>) obj) {
                if (!first) sb.append(',');
                first = false;
                sb.append(toJson(e));
            }
            return sb.append(']').toString();
        }
        return jsonString(String.valueOf(obj));
    }

    private static String jsonString(String s) {
        StringBuilder sb = new StringBuilder("\"");
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"':  sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
            }
        }
        return sb.append('"').toString();
    }

    /** FileSystem-based DocumentInput，避开 Spring 容器。 */
    static class FileDocumentInput implements DocumentInput {
        private final UUID documentId;
        private final String filename;
        private final String contentType;
        private final Path source;

        FileDocumentInput(UUID documentId, String filename, String contentType, Path source) {
            this.documentId = documentId;
            this.filename = filename;
            this.contentType = contentType;
            this.source = source;
        }

        @Override public UUID documentId() { return documentId; }
        @Override public String filename() { return filename; }
        @Override public String contentType() { return contentType; }
        @Override public String sourcePath() { return source.toString(); }
        @Override
        public InputStream openStream() throws IOException {
            return new BufferedInputStream(Files.newInputStream(source));
        }
    }
}
