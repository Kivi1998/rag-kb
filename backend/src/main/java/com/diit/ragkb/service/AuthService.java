package com.diit.ragkb.service;

import com.diit.ragkb.exception.AccessDeniedException;
import com.diit.ragkb.exception.BusinessConflictException;
import com.diit.ragkb.exception.ResourceNotFoundException;
import com.diit.ragkb.model.User;
import com.diit.ragkb.model.UserStatus;
import com.diit.ragkb.repository.MemberRepository;
import com.diit.ragkb.repository.UserRepository;
import io.jsonwebtoken.Claims;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Pattern;

/**
 * 认证服务:注册/登录/改密/重置
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AuthService {

    private final UserRepository userRepository;
    private final MemberRepository memberRepository;
    private final PasswordService passwordService;
    private final JwtService jwtService;
    private final RedisService redisService;

    // 登录失败计数存储在 User.failedLoginCount(数据库)

    private static final int MAX_LOGIN_FAILURES = 5;
    private static final long LOCK_DURATION_MINUTES = 15;
    private static final Pattern EMAIL_PATTERN = Pattern.compile("^[A-Za-z0-9+_.-]+@[A-Za-z0-9.-]+$");
    private static final Pattern PASSWORD_PATTERN = Pattern.compile("^(?=.*[A-Za-z])(?=.*\\d).{8,}$");

    /**
     * 注册
     *
     * @return Map 包含 token 和 userId
     */
    @Transactional
    public Map<String, Object> register(String email, String password, String displayName) {
        // 邮箱格式校验
        if (email == null || !EMAIL_PATTERN.matcher(email).matches()) {
            throw new IllegalArgumentException("邮箱格式不正确");
        }
        // 邮箱唯一性
        if (userRepository.existsByEmail(email)) {
            throw new BusinessConflictException("该邮箱已注册");
        }
        // 密码强度
        validatePassword(password);

        // 创建用户
        User user = new User();
        user.setEmail(email.toLowerCase().trim());
        user.setPasswordHash(passwordService.hash(password));
        user.setDisplayName(displayName != null ? displayName : email.split("@")[0]);
        user = userRepository.save(user);

        // 签发 JWT
        String token = jwtService.generateToken(user.getId(), user.getTokenVersion());

        log.info("用户注册成功: email={}, userId={}", email, user.getId());
        return Map.of("token", token, "userId", user.getId().toString());
    }

    /**
     * 登录
     *
     * @return Map 包含 token 和 userId; 如果 must_change_password 也包含该标记
     */
    @Transactional
    public Map<String, Object> login(String email, String password) {
        String normalizedEmail = email != null ? email.toLowerCase().trim() : "";

        // 查用户
        User user = userRepository.findByEmail(normalizedEmail).orElse(null);
        if (user == null) {
            // 统一返回,不泄露邮箱是否存在
            throw new com.diit.ragkb.exception.UnauthenticatedException("邮箱或密码错误");
        }

        // 账号锁定检查
        if (user.getStatus() == UserStatus.LOCKED) {
            if (user.getLockedUntil() != null && Instant.now().isAfter(user.getLockedUntil())) {
                // 自动解锁
                user.setStatus(UserStatus.ACTIVE);
                user.setFailedLoginCount(0);
                user.setLockedUntil(null);
                userRepository.save(user);
            } else {
                throw new com.diit.ragkb.exception.AccountLockedException("账号已锁定,请稍后再试");
            }
        }

        // 密码验证
        if (!passwordService.matches(password, user.getPasswordHash())) {
            handleLoginFailure(user);
            throw new com.diit.ragkb.exception.UnauthenticatedException("邮箱或密码错误");
        }

        // 登录成功:重置失败计数
        user.setFailedLoginCount(0);
        userRepository.save(user);

        // 签发 JWT
        String token = jwtService.generateToken(user.getId(), user.getTokenVersion());

        var result = new java.util.LinkedHashMap<String, Object>();
        result.put("token", token);
        result.put("userId", user.getId().toString());

        // 查找用户的首个组织成员身份，取 orgId（用户无成员记录时 orgId=null）
        memberRepository.findFirstBySubjectIdOrderByCreatedAtAsc(user.getId().toString())
                .ifPresent(member -> result.put("orgId", member.getOrg().getId().toString()));

        if (user.isMustChangePassword()) {
            result.put("mustChangePassword", true);
        }
        return result;
    }

    /**
     * 用户修改密码
     * 事务提交后再将当前 JWT jti 写入 Redis 黑名单(确保原子性)
     */
    @Transactional
    public void changePassword(UUID userId, String oldPassword, String newPassword,
                               String currentJti, long remainingSeconds) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new ResourceNotFoundException("用户不存在"));

        if (!passwordService.matches(oldPassword, user.getPasswordHash())) {
            throw new com.diit.ragkb.exception.UnauthenticatedException("旧密码错误");
        }
        validatePassword(newPassword);

        user.setPasswordHash(passwordService.hash(newPassword));
        user.setMustChangePassword(false);
        userRepository.save(user);

        // 事务提交后再写 Redis(避免 DB 成功但 Redis 失败导致不一致)
        org.springframework.transaction.support.TransactionSynchronizationManager
                .registerSynchronization(new org.springframework.transaction.support.TransactionSynchronization() {
                    @Override
                    public void afterCommit() {
                        blacklistToken(currentJti, remainingSeconds);
                    }
                });

        log.info("用户修改密码成功: userId={}", userId);
    }

    /**
     * 管理员重置成员密码
     *
     * @return 临时密码
     */
    @Transactional
    public String adminResetPassword(UUID callerMemberId, UUID targetUserId, String callerRole) {
        // 权限检查
        if (!"OWNER".equals(callerRole) && !"ADMIN".equals(callerRole)) {
            throw new AccessDeniedException("只有 owner/admin 可以重置密码");
        }

        User targetUser = userRepository.findById(targetUserId)
                .orElseThrow(() -> new ResourceNotFoundException("用户不存在"));

        // 生成临时密码
        String tempPassword = generateTempPassword();
        targetUser.setPasswordHash(passwordService.hash(tempPassword));
        targetUser.setMustChangePassword(true);
        targetUser.setTokenVersion(targetUser.getTokenVersion() + 1); // 旧 JWT 全部失效
        userRepository.save(targetUser);

        log.info("管理员重置密码: targetUserId={}, callerMemberId={}", targetUserId, callerMemberId);
        return tempPassword;
    }

    /**
     * 将当前 JWT jti 加入黑名单
     */
    public void blacklistToken(String jti, long remainingSeconds) {
        if (jti != null && remainingSeconds > 0) {
            redisService.setWithTTL("blacklist:jti:" + jti, "1", remainingSeconds);
        }
    }

    /**
     * 检查 JWT jti 是否在黑名单中
     */
    public boolean isTokenBlacklisted(String jti) {
        return jti != null && redisService.exists("blacklist:jti:" + jti);
    }

    /**
     * 获取用户的 token_version
     */
    public int getTokenVersion(UUID userId) {
        return userRepository.findById(userId)
                .map(User::getTokenVersion)
                .orElse(0);
    }

    private void handleLoginFailure(User user) {
        user.setFailedLoginCount(user.getFailedLoginCount() + 1);
        if (user.getFailedLoginCount() >= MAX_LOGIN_FAILURES) {
            user.setStatus(UserStatus.LOCKED);
            user.setLockedUntil(Instant.now().plusSeconds(LOCK_DURATION_MINUTES * 60));
            log.warn("账号锁定: email={}, 锁定至 {}", user.getEmail(), user.getLockedUntil());
        }
        userRepository.save(user);
    }

    private void validatePassword(String password) {
        if (password == null || !PASSWORD_PATTERN.matcher(password).matches()) {
            throw new IllegalArgumentException("密码至少 8 位,必须包含字母和数字");
        }
    }

    private String generateTempPassword() {
        // 12 位: 3 大写 + 3 小写 + 3 数字 + 3 特殊字符
        String upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
        String lower = "abcdefghijklmnopqrstuvwxyz";
        String digits = "0123456789";
        String special = "!@#$%^&*";
        java.security.SecureRandom random = new java.security.SecureRandom();
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 3; i++) sb.append(upper.charAt(random.nextInt(upper.length())));
        for (int i = 0; i < 3; i++) sb.append(lower.charAt(random.nextInt(lower.length())));
        for (int i = 0; i < 3; i++) sb.append(digits.charAt(random.nextInt(digits.length())));
        for (int i = 0; i < 3; i++) sb.append(special.charAt(random.nextInt(special.length())));
        // 打乱顺序
        char[] chars = sb.toString().toCharArray();
        for (int i = chars.length - 1; i > 0; i--) {
            int j = random.nextInt(i + 1);
            char tmp = chars[i]; chars[i] = chars[j]; chars[j] = tmp;
        }
        return new String(chars);
    }

}
