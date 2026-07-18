package com.diit.ragkb.ragcore.quickdocument;

import com.diit.ragkb.config.RagQuickDocumentProperties;
import com.diit.ragkb.ragcore.model.DocumentInput;
import com.diit.ragkb.ragcore.model.DocumentSection;
import com.diit.ragkb.ragcore.model.ParsedDocument;
import com.diit.ragkb.ragcore.parser.impl.DocumentParserFactory;
import lombok.RequiredArgsConstructor;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * 会话内临时文档的解析、额度校验与存取编排。复用 {@link DocumentParserFactory}（含 OCR/ASR
 * 网关自动降级），不新写解析逻辑；不切块、不向量化、不写入知识库索引。
 */
@RequiredArgsConstructor
public class QuickDocumentService {

    private final DocumentParserFactory parserFactory;
    private final QuickDocumentStore store;
    private final RagQuickDocumentProperties properties;

    /**
     * 同步解析并存储。字符预算超出会话已用额度时抛出 {@link QuotaExceededException}，
     * 不写入任何数据（无论 Redis 还是解析中间产物）。
     */
    public QuickDocument upload(UUID sessionId, MultipartFile file) throws IOException {
        UUID docId = UUID.randomUUID();
        ParsedDocument parsed = parserFactory.parse(new MultipartDocumentInput(docId, file));
        String content = parsed.sections().stream().map(DocumentSection::text).collect(Collectors.joining("\n\n"));

        int existingCharacters = totalCharacters(sessionId);
        int newCharacters = content.length();
        if (existingCharacters + newCharacters > properties.getMaxTotalCharacters()) {
            throw new QuotaExceededException(existingCharacters, newCharacters, properties.getMaxTotalCharacters());
        }

        QuickDocument document = new QuickDocument(docId, sessionId, file.getOriginalFilename(), content,
                newCharacters, Instant.now());
        store.save(document);
        return document;
    }

    public List<QuickDocument> list(UUID sessionId) {
        return store.findAllBySession(sessionId);
    }

    public void delete(UUID sessionId, UUID docId) {
        store.delete(sessionId, docId);
    }

    private int totalCharacters(UUID sessionId) {
        return store.findAllBySession(sessionId).stream().mapToInt(QuickDocument::characterCount).sum();
    }

    /** 会话临时文档总额度池已满，拒绝本次上传；继承 IllegalArgumentException 复用现有 400 映射。 */
    public static final class QuotaExceededException extends IllegalArgumentException {
        public QuotaExceededException(int existingCharacters, int newCharacters, int maxTotalCharacters) {
            super("会话临时文档总额已满（已用 " + existingCharacters + " + 本次 " + newCharacters + " > 上限 "
                    + maxTotalCharacters + " 字符），请先删除一个再上传");
        }
    }

    private record MultipartDocumentInput(UUID documentId, MultipartFile file) implements DocumentInput {
        @Override public String filename() { return file.getOriginalFilename(); }
        @Override public String contentType() { return file.getContentType(); }
        @Override public String sourcePath() { return "quickdoc/" + documentId; }
        @Override public InputStream openStream() throws IOException { return file.getInputStream(); }
    }
}
