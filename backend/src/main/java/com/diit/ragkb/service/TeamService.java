package com.diit.ragkb.service;

import com.diit.ragkb.exception.ResourceNotFoundException;
import com.diit.ragkb.model.Organization;
import com.diit.ragkb.model.Team;
import com.diit.ragkb.repository.OrganizationRepository;
import com.diit.ragkb.repository.TeamRepository;
import com.diit.ragkb.security.TenantContext;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.UUID;

/**
 * 团队服务
 *
 * 创建团队时校验:父组织必须等于当前租户上下文的 org_id
 */
@Service
@RequiredArgsConstructor
public class TeamService {

    private final TeamRepository teamRepository;
    private final OrganizationRepository orgRepository;

    /**
     * 创建团队
     *
     * @param name 团队名称
     * @return 新建的团队
     * @throws IllegalArgumentException 父组织与当前上下文不匹配(跨组织)
     */
    @Transactional
    public Team create(String name) {
        UUID currentOrgId = TenantContext.getOrgId();
        Organization org = orgRepository.findById(currentOrgId)
                .orElseThrow(() -> new ResourceNotFoundException("组织不存在"));

        Team team = new Team();
        team.setOrg(org);
        team.setName(name);
        return teamRepository.save(team);
    }

    @Transactional(readOnly = true)
    public List<Team> listByCurrentOrg() {
        return teamRepository.findByOrgId(TenantContext.getOrgId());
    }

    @Transactional(readOnly = true)
    public Team getByIdAndCurrentOrg(UUID teamId) {
        return teamRepository.findByIdAndOrgId(teamId, TenantContext.getOrgId())
                .orElseThrow(() -> new ResourceNotFoundException("团队不存在"));
    }
}
