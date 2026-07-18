package com.diit.ragkb.ragcore.ingestion;

import com.diit.ragkb.model.KnowledgeBase;
import com.diit.ragkb.model.KnowledgeDocument;
import com.diit.ragkb.model.Organization;
import com.diit.ragkb.ragcore.index.LexicalChunkIndex;
import com.diit.ragkb.ragcore.index.VectorChunkIndex;
import com.diit.ragkb.ragcore.model.IngestionStatus;
import com.diit.ragkb.ragcore.storage.ObjectStorage;
import com.diit.ragkb.repository.IngestionJobRepository;
import com.diit.ragkb.repository.KnowledgeDocumentRepository;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;
import org.springframework.beans.factory.ObjectProvider;

import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class DocumentDeletionServiceTest {

    @Test
    void deletesInVisibilityVectorLexicalObjectMetadataOrder() throws Exception {
        Fixture fixture = fixture();

        assertTrue(fixture.service.cleanup(fixture.document.getId()));

        UUID orgId = fixture.document.getOrg().getId();
        UUID kbId = fixture.document.getKnowledgeBase().getId();
        InOrder order = inOrder(fixture.lexical, fixture.vector, fixture.storage,
                fixture.jobRepository, fixture.documentRepository);
        order.verify(fixture.lexical).deactivateDocument(orgId, kbId, fixture.document.getId());
        order.verify(fixture.vector).deleteByDocumentId(orgId, kbId, fixture.document.getId());
        order.verify(fixture.lexical).deleteByDocumentId(orgId, kbId, fixture.document.getId());
        order.verify(fixture.storage).delete("original/doc.pdf");
        order.verify(fixture.storage).delete("parsed/doc.json");
        order.verify(fixture.jobRepository).deleteByDocumentId(fixture.document.getId());
        order.verify(fixture.documentRepository).delete(fixture.document);
    }

    @Test
    void vectorFailureKeepsDocumentDeletingAndDoesNotExposeOrRemoveEsBody() throws Exception {
        Fixture fixture = fixture();
        doThrow(new RuntimeException("milvus unavailable"))
                .when(fixture.vector).deleteByDocumentId(any(), any(), any());

        assertFalse(fixture.service.cleanup(fixture.document.getId()));

        verify(fixture.lexical).deactivateDocument(fixture.document.getOrg().getId(),
                fixture.document.getKnowledgeBase().getId(), fixture.document.getId());
        verify(fixture.lexical, never()).deleteByDocumentId(any(), any(), any());
        verify(fixture.storage, never()).delete(any());
        verify(fixture.documentRepository, never()).delete(any());
    }

    @Test
    void missingDocumentMakesRepeatedCleanupIdempotent() {
        Fixture fixture = fixture();
        when(fixture.documentRepository.findById(fixture.document.getId())).thenReturn(Optional.empty());

        assertTrue(fixture.service.cleanup(fixture.document.getId()));
        assertTrue(fixture.service.cleanup(fixture.document.getId()));

        verify(fixture.lexical, never()).deactivateDocument(any(), any(), any());
        verify(fixture.vector, never()).deleteByDocumentId(any(), any(), any());
    }

    @SuppressWarnings("unchecked")
    private Fixture fixture() {
        KnowledgeDocumentRepository documentRepository = mock(KnowledgeDocumentRepository.class);
        IngestionJobRepository jobRepository = mock(IngestionJobRepository.class);
        ObjectStorage storage = mock(ObjectStorage.class);
        LexicalChunkIndex lexical = mock(LexicalChunkIndex.class);
        VectorChunkIndex vector = mock(VectorChunkIndex.class);
        ObjectProvider<LexicalChunkIndex> lexicalProvider = mock(ObjectProvider.class);
        ObjectProvider<VectorChunkIndex> vectorProvider = mock(ObjectProvider.class);
        when(lexicalProvider.getIfAvailable()).thenReturn(lexical);
        when(vectorProvider.getIfAvailable()).thenReturn(vector);

        Organization org = new Organization();
        org.setId(UUID.randomUUID());
        KnowledgeBase kb = new KnowledgeBase();
        kb.setId(UUID.randomUUID());
        kb.setOrg(org);
        KnowledgeDocument document = new KnowledgeDocument();
        document.setId(UUID.randomUUID());
        document.setOrg(org);
        document.setKnowledgeBase(kb);
        document.setStatus(IngestionStatus.DELETING);
        document.setObjectStoragePath("original/doc.pdf");
        document.setParseArtifactPath("parsed/doc.json");
        when(documentRepository.findById(document.getId())).thenReturn(Optional.of(document));

        DocumentDeletionService service = new DocumentDeletionService(documentRepository, jobRepository,
                storage, lexicalProvider, vectorProvider);
        return new Fixture(service, document, documentRepository, jobRepository, storage, lexical, vector);
    }

    private record Fixture(DocumentDeletionService service, KnowledgeDocument document,
                           KnowledgeDocumentRepository documentRepository,
                           IngestionJobRepository jobRepository, ObjectStorage storage,
                           LexicalChunkIndex lexical, VectorChunkIndex vector) { }
}
