package com.diit.ragkb.service;

import com.diit.ragkb.exception.ResourceNotFoundException;
import com.diit.ragkb.model.KbStatus;
import com.diit.ragkb.model.KnowledgeBase;
import com.diit.ragkb.model.Organization;
import com.diit.ragkb.repository.KnowledgeBaseRepository;
import com.diit.ragkb.repository.MemberRepository;
import com.diit.ragkb.repository.OrganizationRepository;
import com.diit.ragkb.security.TenantContext;
import com.diit.ragkb.service.ragflow.RagFlowClient;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.UUID;

/**
 * 知识库服务
 *
 * 创建:先建 RAGFlow dataset(带归属标签) → 再落库,任一步失败整体回滚
 * 删除:先删 RAGFlow dataset → 再删记录;dataset 删除失败则标记 PENDING_CLEANUP 转对账
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class KnowledgeBaseService {

    private final KnowledgeBaseRepository kbRepository;
    private final OrganizationRepository orgRepository;
    private final MemberRepository memberRepository;
    private final RagFlowClient ragFlowClient;

    /**
     * 创建知识库
     * 1. 创建带归属标签的 RAGFlow dataset(幂等)
     * 2. 保存知识库记录(与 dataset 映射)
     * 失败则整体回滚,不留半成品
     */
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
        kb = kbRepository.save(kb); // 先落库拿 ID

        // 创建 dataset(带归属标签:ragkb:{kbId},description 含 orgId 用于对账)
        String datasetId = ragFlowClient.createDataset(
                "ragkb:" + kb.getId(),                          // name = ragkb:{kbId}
                "ragkb:" + currentOrgId + ":" + kb.getId());    // description = ragkb:{orgId}:{kbId}
        kb.setRagflowDatasetId(datasetId);
        kb.setStatus(KbStatus.ACTIVE);
        return kbRepository.save(kb);
    }

    @Transactional
    public KnowledgeBase update(UUID kbId, String newName) {
        KnowledgeBase kb = getByIdAndCurrentOrg(kbId);
        kb.setName(newName);
        return kbRepository.save(kb);
    }

    /**
     * 删除知识库
     * 顺序:先删 RAGFlow dataset → 再删记录
     * dataset 删除失败:记录置 PENDING_CLEANUP,转对账(不 throw,避免回滚导致标记丢失)
     *
     * @return true=完全删除,false=dataset 删除失败,已标记待对账
     */
    @Transactional
    public boolean delete(UUID kbId) {
        KnowledgeBase kb = getByIdAndCurrentOrg(kbId);

        // 先删 Chat Assistant(可为 null 时跳过)
        try {
            ragFlowClient.deleteChat(kb.getRagflowChatId());
        } catch (Exception e) {
            // Chat 删除失败:标记待清理,但不阻塞后续 dataset 删除
            log.warn("删除 Chat Assistant 失败,kbId={},标记待清理: {}", kbId, e.getMessage());
            kb.setStatus(KbStatus.PENDING_CLEANUP);
            kbRepository.save(kb);
            return false;
        }

        // 再删 dataset
        try {
            ragFlowClient.deleteDataset(kb.getRagflowDatasetId());
        } catch (Exception e) {
            log.warn("删除 dataset 失败,kbId={},标记待清理: {}", kbId, e.getMessage());
            kb.setStatus(KbStatus.PENDING_CLEANUP);
            kbRepository.save(kb);
            // 不 throw —— 避免事务回滚导致 PENDING_CLEANUP 标记丢失
            return false;
        }

        // 删记录
        kbRepository.delete(kb);
        log.info("知识库已删除,kbId={},datasetId={}", kbId, kb.getRagflowDatasetId());
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
