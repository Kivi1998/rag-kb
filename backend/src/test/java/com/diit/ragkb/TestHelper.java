package com.diit.ragkb;

import com.diit.ragkb.model.Member;
import com.diit.ragkb.model.MemberRole;
import com.diit.ragkb.model.Organization;
import com.diit.ragkb.model.User;
import com.diit.ragkb.repository.MemberRepository;
import com.diit.ragkb.repository.OrganizationRepository;
import com.diit.ragkb.repository.UserRepository;
import com.diit.ragkb.service.JwtService;
import com.diit.ragkb.service.PasswordService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

/**
 * 测试工具:创建组织/成员/用户,生成 JWT
 */
@Component
public class TestHelper {

    @Autowired private OrganizationRepository orgRepository;
    @Autowired private MemberRepository memberRepository;
    @Autowired private UserRepository userRepository;
    @Autowired private JwtService jwtService;
    @Autowired private PasswordService passwordService;

    /** 创建组织 */
    public Organization createOrg(String name) {
        Organization org = new Organization();
        org.setName(name);
        return orgRepository.save(org);
    }

    /** 在组织内创建成员 */
    public Member createMember(String subjectId, Organization org, MemberRole role) {
        Member member = new Member();
        member.setSubjectId(subjectId);
        member.setOrg(org);
        member.setRole(role);
        return memberRepository.save(member);
    }

    /** 创建用户并返回 */
    public User createUser(String email, String rawPassword, String displayName) {
        User user = new User();
        user.setEmail(email);
        user.setPasswordHash(passwordService.hash(rawPassword));
        user.setDisplayName(displayName != null ? displayName : email.split("@")[0]);
        return userRepository.save(user);
    }

    /** 用 JwtService 签发 JWT(与生产一致) */
    public String generateToken(String userId) {
        return jwtService.generateToken(java.util.UUID.fromString(userId), 0);
    }

    /** 用 JwtService 签发 JWT(指定 tokenVersion) */
    public String generateToken(java.util.UUID userId, int tokenVersion) {
        return jwtService.generateToken(userId, tokenVersion);
    }
}
