package com.diit.ragkb.ragcore.quickdocument;

import com.diit.ragkb.config.RagQuickDocumentProperties;
import com.diit.ragkb.ragcore.parser.impl.DocumentParserFactory;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.mock.web.MockMultipartFile;

import java.io.IOException;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** 用真实 DocumentParserFactory（Markdown 本地解析，不依赖网关）跑，只 mock 存取层与配置。 */
class QuickDocumentServiceTest {

    private final DocumentParserFactory parserFactory = DocumentParserFactory.createDefault();

    @Test
    void uploadParsesAndSavesWithinQuota() throws IOException {
        QuickDocumentStore store = mock(QuickDocumentStore.class);
        UUID sessionId = UUID.randomUUID();
        when(store.findAllBySession(sessionId)).thenReturn(List.of());
        RagQuickDocumentProperties properties = properties(15000);
        QuickDocumentService service = new QuickDocumentService(parserFactory, store, properties);
        MockMultipartFile file = new MockMultipartFile("file", "笔记.md", "text/markdown", "# 标题\n正文内容".getBytes());

        QuickDocument result = service.upload(sessionId, file);

        assertEquals(sessionId, result.sessionId());
        assertEquals("笔记.md", result.filename());
        assertTrue(result.characterCount() > 0);
        ArgumentCaptor<QuickDocument> captor = ArgumentCaptor.forClass(QuickDocument.class);
        verify(store).save(captor.capture());
        assertEquals(result.docId(), captor.getValue().docId());
    }

    @Test
    void uploadRejectsWhenExceedingSessionQuota() {
        QuickDocumentStore store = mock(QuickDocumentStore.class);
        UUID sessionId = UUID.randomUUID();
        QuickDocument existing = new QuickDocument(UUID.randomUUID(), sessionId, "已有.md", "x".repeat(20), 20,
                Instant.now());
        when(store.findAllBySession(sessionId)).thenReturn(List.of(existing));
        RagQuickDocumentProperties properties = properties(25); // 已用 20，新文档解析后必然超过 25
        QuickDocumentService service = new QuickDocumentService(parserFactory, store, properties);
        MockMultipartFile file = new MockMultipartFile("file", "超额.md", "text/markdown",
                "# 一个明显超过剩余额度的很长标题和很长正文内容".getBytes());

        assertThrows(QuickDocumentService.QuotaExceededException.class, () -> service.upload(sessionId, file));
        verify(store, never()).save(org.mockito.ArgumentMatchers.any());
    }

    @Test
    void uploadRejectsUnsupportedFormat() {
        QuickDocumentStore store = mock(QuickDocumentStore.class);
        UUID sessionId = UUID.randomUUID();
        when(store.findAllBySession(sessionId)).thenReturn(List.of());
        QuickDocumentService service = new QuickDocumentService(parserFactory, store, properties(15000));
        MockMultipartFile file = new MockMultipartFile("file", "unsafe.exe", "application/octet-stream",
                new byte[]{1, 2, 3});

        assertThrows(IOException.class, () -> service.upload(sessionId, file));
        verify(store, never()).save(org.mockito.ArgumentMatchers.any());
    }

    @Test
    void multipleDocumentsShareTheSameQuotaPool() throws IOException {
        QuickDocumentStore store = mock(QuickDocumentStore.class);
        UUID sessionId = UUID.randomUUID();
        // 第一次上传时会话内还没有文档；模拟第一次 save() 之后第二次查询已经能看到它。
        QuickDocument first = new QuickDocument(UUID.randomUUID(), sessionId, "第一份.md", "y".repeat(40), 40,
                Instant.now());
        when(store.findAllBySession(sessionId)).thenReturn(List.of()).thenReturn(List.of(first));
        RagQuickDocumentProperties properties = properties(50);
        QuickDocumentService service = new QuickDocumentService(parserFactory, store, properties);

        service.upload(sessionId, new MockMultipartFile("file", "a.md", "text/markdown", "短".getBytes()));

        assertThrows(QuickDocumentService.QuotaExceededException.class, () -> service.upload(sessionId,
                new MockMultipartFile("file", "b.md", "text/markdown",
                        "# 第二份文档正文明显超过剩余额度池空间".getBytes())));
    }

    private RagQuickDocumentProperties properties(int maxTotalCharacters) {
        RagQuickDocumentProperties properties = new RagQuickDocumentProperties();
        properties.setMaxTotalCharacters(maxTotalCharacters);
        return properties;
    }
}
