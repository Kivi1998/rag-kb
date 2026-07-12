package com.diit.ragkb.repository;

import com.diit.ragkb.model.QueryAuditLog;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.UUID;

public interface QueryAuditLogRepository extends JpaRepository<QueryAuditLog, UUID> {
}
