package com.diit.ragkb.service;

import com.diit.ragkb.model.Member;
import com.diit.ragkb.model.MemberRole;
import com.diit.ragkb.model.Organization;
import com.diit.ragkb.repository.MemberRepository;
import com.diit.ragkb.repository.OrganizationRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 组织服务
 *
 * 创建组织 = bootstrap:免租户上下文,创建后 subject 自动成为 owner
 */
@Service
@RequiredArgsConstructor
public class OrganizationService {

    private final OrganizationRepository orgRepository;
    private final MemberRepository memberRepository;

    /**
     * 创建组织,并将 subject 注册为该组织首个 owner
     *
     * @param subjectId 认证主体标识(来自 JWT sub)
     * @param name      组织名称
     * @return 新建的组织
     */
    @Transactional
    public Organization create(String subjectId, String name) {
        // 创建组织
        Organization org = new Organization();
        org.setName(name);
        org = orgRepository.save(org);

        // subject 自动成为该组织 owner(bootstrap)
        Member owner = new Member();
        owner.setSubjectId(subjectId);
        owner.setOrg(org);
        owner.setRole(MemberRole.OWNER);
        memberRepository.save(owner);

        return org;
    }

    @Transactional(readOnly = true)
    public Organization getById(java.util.UUID orgId) {
        return orgRepository.findById(orgId)
                .orElseThrow(() -> new com.diit.ragkb.exception.ResourceNotFoundException("组织不存在"));
    }
}
