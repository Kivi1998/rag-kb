package com.diit.ragkb.ragcore.ingestion;

import com.diit.ragkb.model.IngestionJob;
import com.diit.ragkb.model.KnowledgeDocument;
import com.diit.ragkb.ragcore.model.IngestionStatus;
import com.diit.ragkb.repository.IngestionJobRepository;
import com.diit.ragkb.repository.KnowledgeDocumentRepository;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.time.Duration;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class IngestionLeaseFencingTest {

    @Test
    void staleWorkerCannotAdvanceFailOrPublishArtifactAfterLeaseTakeover() {
        IngestionJobRepository jobs = mock(IngestionJobRepository.class);
        KnowledgeDocumentRepository documents = mock(KnowledgeDocumentRepository.class);
        IngestionJobLifecycleService lifecycle = new IngestionJobLifecycleService(jobs, documents);

        UUID jobId = UUID.randomUUID();
        KnowledgeDocument document = new KnowledgeDocument();
        document.setId(UUID.randomUUID());
        document.setStatus(IngestionStatus.PARSING);
        IngestionJob job = new IngestionJob();
        job.setId(jobId);
        job.setAttempt(2);
        job.setLeaseOwner("worker-new");
        job.setLeaseExpiresAt(Instant.now().plusSeconds(60));
        job.setStatus(IngestionStatus.PARSING);
        job.setDocument(document);
        when(jobs.findByIdForUpdate(jobId)).thenReturn(Optional.of(job));

        IngestionTask stale = task(jobId, 1, "worker-old", document.getId());
        assertThrows(StaleIngestionLeaseException.class,
                () -> lifecycle.advance(stale, IngestionStatus.CHUNKING));
        assertThrows(StaleIngestionLeaseException.class,
                () -> lifecycle.recordParsedArtifact(stale, "artifact.json", "parser", "1"));
        assertThrows(StaleIngestionLeaseException.class,
                () -> lifecycle.fail(stale, new IllegalStateException("old worker failed")));

        assertEquals(IngestionStatus.PARSING, job.getStatus());
        assertEquals(IngestionStatus.PARSING, document.getStatus());
        verifyNoInteractions(documents);

        lifecycle.advance(task(jobId, 2, "worker-new", document.getId()), IngestionStatus.CHUNKING);
        assertEquals(IngestionStatus.CHUNKING, job.getStatus());
        assertEquals(IngestionStatus.CHUNKING, document.getStatus());
    }

    @Test
    void expiredLeaseCannotBeResurrectedByHeartbeatOrStageCommit() {
        IngestionJobRepository jobs = mock(IngestionJobRepository.class);
        IngestionJobLifecycleService lifecycle = new IngestionJobLifecycleService(
                jobs, mock(KnowledgeDocumentRepository.class));
        UUID jobId = UUID.randomUUID();
        KnowledgeDocument document = new KnowledgeDocument();
        document.setId(UUID.randomUUID());
        IngestionJob job = new IngestionJob();
        job.setId(jobId);
        job.setAttempt(3);
        job.setLeaseOwner("worker-same-id");
        job.setLeaseExpiresAt(Instant.now().minusSeconds(1));
        job.setStatus(IngestionStatus.PARSING);
        job.setDocument(document);
        when(jobs.findByIdForUpdate(jobId)).thenReturn(Optional.of(job));
        IngestionTask expired = task(jobId, 3, "worker-same-id", document.getId());

        assertThrows(StaleIngestionLeaseException.class,
                () -> lifecycle.advance(expired, IngestionStatus.CHUNKING));
        assertFalse(lifecycle.heartbeat(expired, Duration.ofMinutes(2)));
        verify(jobs).heartbeat(eq(jobId), eq("worker-same-id"), eq(3), any(), any(), any());
    }

    private IngestionTask task(UUID jobId, int attempt, String leaseOwner, UUID documentId) {
        return new IngestionTask(jobId, attempt, leaseOwner, documentId, UUID.randomUUID(), UUID.randomUUID(),
                "scan.pdf", "application/pdf", "org/source.pdf", null, null);
    }
}
