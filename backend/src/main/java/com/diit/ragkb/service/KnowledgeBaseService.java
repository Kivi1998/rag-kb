package com.diit.ragkb.service;

import com.diit.ragkb.exception.ResourceNotFoundException;
import com.diit.ragkb.model.KbStatus;
import com.diit.ragkb.model.KnowledgeBase;
import com.diit.ragkb.model.Organization;
import com.diit.ragkb.repository.KnowledgeBaseRepository;
import com.diit.ragkb.repository.MemberRepository;
import com.diit.ragkb.repository.OrganizationRepository;
import com.diit.ragkb.security.TenantContext;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.UUID;

/**
 * 知识库服务
 *
 * RAG 核心重构期间仅负责知识库业务元数据。
 * 文档摄取、索引与问答将在新的 ragcore 模块完成后重新接入。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class KnowledgeBaseService {

    private final KnowledgeBaseRepository kbRepository;
    private final OrganizationRepository orgRepository;
    private final MemberRepository memberRepository;
    /** 创建知识库业务记录。 */
    @Transactional
    public KnowledgeBase create(String name) {
        UUID currentOrgId = TenantContext.getOrgId();
        Organization org = orgRepository.findById(currentOrgId)
                .orElseThrow(() -> new ResourceNotFoundException("组织不存在"));

        // 创建者信息
        com.diit.ragkb.model.Member creator = memberRepository
                .findById(TenantContext.getMemberId())
                .orElseThrow(() -> new com.diit.ragkb.exception.ResourceNotFoundException("成员不存在"));

        KnowledgeBase kb = new KnowledgeBase();
        kb.setOrg(org);
        kb.setName(name);
        kb.setCreatedBy(creator);
        kb.setStatus(KbStatus.ACTIVE);
        return kbRepository.save(kb);
    }

    @Transactional
    public KnowledgeBase update(UUID kbId, String newName) {
        KnowledgeBase kb = getByIdAndCurrentOrg(kbId);
        kb.setName(newName);
        return kbRepository.save(kb);
    }

    /** 删除知识库业务记录。 */
    @Transactional
    public boolean delete(UUID kbId) {
        KnowledgeBase kb = getByIdAndCurrentOrg(kbId);

        kbRepository.delete(kb);
        log.info("知识库已删除,kbId={}", kbId);
        return true;
    }

    @Transactional(readOnly = true)
    public KnowledgeBase getByIdAndCurrentOrg(UUID kbId) {
        return kbRepository.findByIdAndOrgId(kbId, TenantContext.getOrgId())
                .orElseThrow(() -> new ResourceNotFoundException("知识库不存在"));
    }

    @Transactional(readOnly = true)
    public List<KnowledgeBase> listByCurrentOrg() {
        return kbRepository.findByOrgId(TenantContext.getOrgId());
    }
}
