package com.diit.ragkb.repository;

import com.diit.ragkb.model.Member;
import com.diit.ragkb.model.MemberRole;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface MemberRepository extends JpaRepository<Member, UUID> {

    List<Member> findByOrgId(UUID orgId);

    Optional<Member> findByIdAndOrgId(UUID id, UUID orgId);

    /** 查某 subject 在某组织的 member 记录 */
    Optional<Member> findBySubjectIdAndOrgId(String subjectId, UUID orgId);

    /** 某组织内 owner 数量 */
    long countByOrgIdAndRole(UUID orgId, MemberRole role);

    /** 查某 subject 的首个成员记录（按创建时间升序） */
    Optional<Member> findFirstBySubjectIdOrderByCreatedAtAsc(String subjectId);
}
