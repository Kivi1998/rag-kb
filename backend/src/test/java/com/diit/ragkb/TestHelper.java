package com.diit.ragkb;

import com.diit.ragkb.model.Member;
import com.diit.ragkb.model.MemberRole;
import com.diit.ragkb.model.Organization;
import com.diit.ragkb.repository.MemberRepository;
import com.diit.ragkb.repository.OrganizationRepository;
import io.jsonwebtoken.Jwts;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;

/**
 * 测试工具:创建组织/成员,生成 JWT
 */
@Component
public class TestHelper {

    @Autowired
    private OrganizationRepository orgRepository;
    @Autowired
    private MemberRepository memberRepository;

    @Value("${spring.security.jwt.secret}")
    private String jwtSecret;

    /** 创建组织并返回(subject 自动成为 owner) */
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

    /** 生成 JWT token */
    public String generateToken(String subjectId) {
        SecretKey key = Keys.hmacShaKeyFor(jwtSecret.getBytes(StandardCharsets.UTF_8));
        return Jwts.builder()
                .subject(subjectId)
                .signWith(key)
                .compact();
    }
}
