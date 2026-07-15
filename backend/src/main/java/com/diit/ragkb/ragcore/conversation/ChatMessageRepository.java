package com.diit.ragkb.ragcore.conversation;

import org.springframework.data.mongodb.repository.MongoRepository;

import java.util.List;
import java.util.UUID;

public interface ChatMessageRepository extends MongoRepository<ChatMessageDocument, String> {

    List<ChatMessageDocument> findBySessionIdAndOrganizationIdOrderByCreatedAtAsc(UUID sessionId, UUID organizationId);
}
