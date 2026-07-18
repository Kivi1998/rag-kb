package com.diit.ragkb.service;

import com.diit.ragkb.TestHelper;
import com.diit.ragkb.config.TenantHibernateFilterConfig;
import com.diit.ragkb.model.IntentTrainingSample;
import com.diit.ragkb.model.KnowledgeBase;
import com.diit.ragkb.model.Member;
import com.diit.ragkb.model.MemberRole;
import com.diit.ragkb.model.Organization;
import com.diit.ragkb.model.User;
import com.diit.ragkb.repository.IntentTrainingSampleRepository;
import com.diit.ragkb.repository.KnowledgeBaseRepository;
import com.diit.ragkb.repository.MemberRepository;
import com.diit.ragkb.repository.OrganizationRepository;
import com.diit.ragkb.repository.UserRepository;
import com.diit.ragkb.security.TenantContext;
import jakarta.persistence.EntityManager;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 验证 {@link IntentTrainingSample} 参与既有的 Hibernate {@code tenantFilter} 二道防线
 * （见 {@link TenantHibernateFilterConfig}）——本表存问题原文，敏感度高于 rag_query_audit，
 * 即使本次不新增读取该表的 API，也要确认表结构/实体层面的隔离能力从一开始就到位。
 */
@SpringBootTest
@DisplayName("意图训练样本表跨租户隔离")
class IntentTrainingSampleTenantIsolationTest {

    @Autowired private TestHelper testHelper;
    @Autowired private IntentTrainingSampleRepository repository;
    @Autowired private KnowledgeBaseRepository knowledgeBaseRepository;
    @Autowired private MemberRepository memberRepository;
    @Autowired private OrganizationRepository organizationRepository;
    @Autowired private UserRepository userRepository;
    @Autowired private TenantHibernateFilterConfig filterConfig;
    @Autowired private EntityManager entityManager;

    private Organization orgA;
    private Organization orgB;
    private KnowledgeBase kbA;
    private KnowledgeBase kbB;
    private Member memberA;
    private Member memberB;

    @BeforeEach
    void setUp() {
        repository.deleteAll();
        knowledgeBaseRepository.deleteAll();
        memberRepository.deleteAll();
        organizationRepository.deleteAll();
        userRepository.deleteAll();

        orgA = testHelper.createOrg("训练样本组织A");
        orgB = testHelper.createOrg("训练样本组织B");
        User userA = testHelper.createUser("intent-a@test.com", "Pass1234!", "A");
        User userB = testHelper.createUser("intent-b@test.com", "Pass1234!", "B");
        memberA = testHelper.createMember(userA.getId().toString(), orgA, MemberRole.OWNER);
        memberB = testHelper.createMember(userB.getId().toString(), orgB, MemberRole.OWNER);

        kbA = new KnowledgeBase();
        kbA.setOrg(orgA);
        kbA.setName("知识库A");
        kbA.setCreatedBy(memberA);
        kbA = knowledgeBaseRepository.save(kbA);

        kbB = new KnowledgeBase();
        kbB.setOrg(orgB);
        kbB.setName("知识库B");
        kbB.setCreatedBy(memberB);
        kbB = knowledgeBaseRepository.save(kbB);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Test
    @Transactional
    @DisplayName("启用 tenantFilter 后只能查到本组织的训练样本")
    void tenantFilterRestrictsQueryToOwnOrganization() {
        saveSample(orgA, kbA, memberA, "NullPointerException 怎么排查？", "precise-lookup");
        saveSample(orgB, kbB, memberB, "为什么要用 L1 范数？", "semantic");
        entityManager.flush();

        TenantContext.set(orgA.getId(), memberA.getId(), "OWNER");
        filterConfig.enableFilter(entityManager);

        List<IntentTrainingSample> visible = repository.findAll();

        assertEquals(1, visible.size());
        assertEquals(orgA.getId(), visible.get(0).getOrgId());
        assertTrue(visible.stream().noneMatch(s -> s.getOrgId().equals(orgB.getId())),
                "跨组织的训练样本（含问题原文）不应出现在查询结果里");
    }

    private void saveSample(Organization org, KnowledgeBase kb, Member member, String question,
                            String predictedIntent) {
        IntentTrainingSample sample = new IntentTrainingSample();
        sample.setOrgId(org.getId());
        sample.setKbId(kb.getId());
        sample.setMemberId(member.getId());
        sample.setQuestion(question);
        sample.setPredictedIntent(predictedIntent);
        repository.save(sample);
    }
}
