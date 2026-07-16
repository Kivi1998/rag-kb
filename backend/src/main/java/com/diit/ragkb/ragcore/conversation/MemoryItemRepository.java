package com.diit.ragkb.ragcore.conversation;

import org.springframework.data.mongodb.repository.MongoRepository;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

public interface MemoryItemRepository extends MongoRepository<MemoryItemDocument, String> {

    List<MemoryItemDocument> findByMemberIdAndOrganizationId(UUID memberId, UUID organizationId);

    List<MemoryItemDocument> findByLastAccessedAtBeforeAndImportanceLessThan(Instant cutoff, double importanceThreshold);
}
