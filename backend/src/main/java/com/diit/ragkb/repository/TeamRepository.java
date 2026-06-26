package com.diit.ragkb.repository;

import com.diit.ragkb.model.Team;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface TeamRepository extends JpaRepository<Team, UUID> {

    List<Team> findByOrgId(UUID orgId);

    Optional<Team> findByIdAndOrgId(UUID id, UUID orgId);
}
