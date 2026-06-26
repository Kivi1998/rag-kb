package com.diit.ragkb.service;

import com.diit.ragkb.exception.AccessDeniedException;
import com.diit.ragkb.exception.BusinessConflictException;
import com.diit.ragkb.exception.ResourceNotFoundException;
import com.diit.ragkb.model.Member;
import com.diit.ragkb.model.MemberRole;
import com.diit.ragkb.model.Organization;
import com.diit.ragkb.repository.MemberRepository;
import com.diit.ragkb.repository.OrganizationRepository;
import com.diit.ragkb.security.TenantContext;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.UUID;

/**
 * 成员服务
 *
 * 角色层级矩阵:
 * - OWNER:  全权(可管理所有成员角色,含 admin;可转让/撤销 owner)
 * - ADMIN:  可管理 MEMBER(邀请/移除/读),但不可设/改 OWNER,不可修改 OWNER
 * - MEMBER: 只读
 *
 * 硬约束:组织始终至少保留一名 owner
 */
@Service
@RequiredArgsConstructor
public class MemberService {

    private final MemberRepository memberRepository;
    private final OrganizationRepository orgRepository;

    /**
     * 邀请成员(在当前组织内)
     *
     * @param subjectId 被邀请的认证主体标识
     * @param role      分配的角色(不能是 OWNER —— owner 只能通过转让)
     * @return 新建的 member
     */
    @Transactional
    public Member invite(String subjectId, MemberRole role) {
        if (role == MemberRole.OWNER) {
            throw new AccessDeniedException("不能直接邀请为 owner,请使用转让 owner 接口");
        }

        UUID currentOrgId = TenantContext.getOrgId();
        MemberRole callerRole = MemberRole.valueOf(TenantContext.getRole());

        // 只有 owner 和 admin 可邀请
        assertCanManage(callerRole, role);

        // 已存在则拒绝
        if (memberRepository.findBySubjectIdAndOrgId(subjectId, currentOrgId).isPresent()) {
            throw new BusinessConflictException("该主体已是本组织成员");
        }

        Organization org = orgRepository.findById(currentOrgId)
                .orElseThrow(() -> new ResourceNotFoundException("组织不存在"));

        Member member = new Member();
        member.setSubjectId(subjectId);
        member.setOrg(org);
        member.setRole(role);
        return memberRepository.save(member);
    }

    /**
     * 修改成员角色
     */
    @Transactional
    public Member changeRole(UUID targetMemberId, MemberRole newRole) {
        UUID currentOrgId = TenantContext.getOrgId();
        MemberRole callerRole = MemberRole.valueOf(TenantContext.getRole());

        Member target = memberRepository.findByIdAndOrgId(targetMemberId, currentOrgId)
                .orElseThrow(() -> new ResourceNotFoundException("成员不存在"));

        // admin 不可设/改 owner
        if (newRole == MemberRole.OWNER && callerRole != MemberRole.OWNER) {
            throw new AccessDeniedException("只有 owner 可以设/改为 owner 角色");
        }

        // 不可修改 owner 的角色(除非是 owner 自己操作)
        if (target.getRole() == MemberRole.OWNER && callerRole != MemberRole.OWNER) {
            throw new AccessDeniedException("只有 owner 可以修改 owner 的角色");
        }

        assertCanManage(callerRole, newRole);

        // 不得降级最后一名 owner
        if (target.getRole() == MemberRole.OWNER && newRole != MemberRole.OWNER) {
            long ownerCount = memberRepository.countByOrgIdAndRole(currentOrgId, MemberRole.OWNER);
            if (ownerCount <= 1) {
                throw new BusinessConflictException("组织必须至少保留一名 owner");
            }
        }

        target.setRole(newRole);
        return memberRepository.save(target);
    }

    @Transactional(readOnly = true)
    public List<Member> listByCurrentOrg() {
        return memberRepository.findByOrgId(TenantContext.getOrgId());
    }

    @Transactional(readOnly = true)
    public Member getByIdAndCurrentOrg(UUID memberId) {
        return memberRepository.findByIdAndOrgId(memberId, TenantContext.getOrgId())
                .orElseThrow(() -> new ResourceNotFoundException("成员不存在"));
    }

    /**
     * 角色层级校验:callerRole 是否可管理 targetRole
     */
    private void assertCanManage(MemberRole callerRole, MemberRole targetRole) {
        switch (callerRole) {
            case OWNER -> {} // owner 全权
            case ADMIN -> {
                if (targetRole == MemberRole.OWNER || targetRole == MemberRole.ADMIN) {
                    throw new AccessDeniedException("admin 只能管理 member 角色");
                }
            }
            default -> throw new AccessDeniedException("member 角色无权执行此操作");
        }
    }
}
