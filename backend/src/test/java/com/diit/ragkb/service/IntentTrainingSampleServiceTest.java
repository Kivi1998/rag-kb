package com.diit.ragkb.service;

import com.diit.ragkb.model.IntentTrainingSample;
import com.diit.ragkb.repository.IntentTrainingSampleRepository;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class IntentTrainingSampleServiceTest {

    @Test
    void recordPersistsAllFields() {
        IntentTrainingSampleRepository repository = mock(IntentTrainingSampleRepository.class);
        IntentTrainingSampleService service = new IntentTrainingSampleService(repository);
        UUID orgId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID memberId = UUID.randomUUID();

        service.record(orgId, kbId, memberId, "NullPointerException 怎么排查？", "precise-lookup");

        ArgumentCaptor<IntentTrainingSample> captor = ArgumentCaptor.forClass(IntentTrainingSample.class);
        verify(repository).save(captor.capture());
        IntentTrainingSample saved = captor.getValue();
        assertEquals(orgId, saved.getOrgId());
        assertEquals(kbId, saved.getKbId());
        assertEquals(memberId, saved.getMemberId());
        assertEquals("NullPointerException 怎么排查？", saved.getQuestion());
        assertEquals("precise-lookup", saved.getPredictedIntent());
    }

    @Test
    void recordSafelySwallowsExceptionAndDoesNotPropagate() {
        IntentTrainingSampleRepository repository = mock(IntentTrainingSampleRepository.class);
        when(repository.save(org.mockito.ArgumentMatchers.any()))
                .thenThrow(new RuntimeException("数据库暂时不可用"));
        IntentTrainingSampleService service = new IntentTrainingSampleService(repository);

        assertDoesNotThrow(() -> service.recordSafely(UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(),
                "问题", "semantic"));
    }
}
