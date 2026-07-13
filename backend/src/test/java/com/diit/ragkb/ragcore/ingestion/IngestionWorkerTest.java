package com.diit.ragkb.ragcore.ingestion;

import com.diit.ragkb.model.IngestionJob;
import com.diit.ragkb.ragcore.model.IngestionStatus;
import com.diit.ragkb.repository.IngestionJobRepository;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class IngestionWorkerTest {

    @Test
    void startsAndCancelsHeartbeatAroundLongRunningPipeline() throws Exception {
        IngestionJobRepository repository = mock(IngestionJobRepository.class);
        IngestionJobLifecycleService lifecycle = mock(IngestionJobLifecycleService.class);
        DocumentIngestionPipeline pipeline = mock(DocumentIngestionPipeline.class);
        ScheduledExecutorService heartbeatExecutor = mock(ScheduledExecutorService.class);
        ScheduledFuture<?> heartbeat = mock(ScheduledFuture.class);

        UUID jobId = UUID.randomUUID();
        IngestionJob job = new IngestionJob();
        job.setId(jobId);
        job.setAttempt(0);
        IngestionTask task = new IngestionTask(jobId, UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(),
                "scan.pdf", "application/pdf", "source/scan.pdf", null, null);
        when(repository.countByStatus(IngestionStatus.QUEUED)).thenReturn(1L);
        when(repository.findByStatusOrderByCreatedAtAsc(eq(IngestionStatus.QUEUED), any()))
                .thenReturn(List.of(job));
        when(lifecycle.claim(eq(jobId), eq("worker-test"), any())).thenReturn(Optional.of(task));
        doReturn(heartbeat).when(heartbeatExecutor)
                .scheduleAtFixedRate(any(Runnable.class), anyLong(), anyLong(), any());

        IngestionWorker worker = new IngestionWorker(repository, lifecycle, pipeline,
                new IngestionMetrics(new SimpleMeterRegistry()), Runnable::run, heartbeatExecutor);
        ReflectionTestUtils.setField(worker, "workerId", "worker-test");
        ReflectionTestUtils.setField(worker, "concurrency", 2);
        ReflectionTestUtils.setField(worker, "batchSize", 2);
        ReflectionTestUtils.setField(worker, "leaseDurationMs", 30_000L);

        worker.poll();

        verify(pipeline).process(task);
        verify(heartbeatExecutor).scheduleAtFixedRate(any(Runnable.class), eq(10_000L), eq(10_000L), any());
        verify(heartbeat).cancel(false);
    }
}
