package com.diit.ragkb.repository;

import com.diit.ragkb.model.IntentTrainingSample;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.UUID;

public interface IntentTrainingSampleRepository extends JpaRepository<IntentTrainingSample, UUID> {
}
