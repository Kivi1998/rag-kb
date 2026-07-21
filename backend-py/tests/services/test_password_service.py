"""密码 hash/verify 服务测试。

对应 Java 版 `service/PasswordService.java`(`BCryptPasswordEncoder(10)`)。
关键不变量:
- hash 出来的字符串用同 verify 函数能验证通过
- 错误密码必须返回 False,不能因为"前缀匹配"误判通过
- 同 strength/rounds 下,生产代码和测试代码生成的哈希可以互相 verify
  ——保证迁移期间不会因算法差异导致存量用户登不进来
- hash 不是明文回写:hash(password) != password
"""

from __future__ import annotations

import re

from app.services.password_service import hash_password, verify_password


class TestHashAndVerifyRoundTrip:
    def test_correct_password_verifies(self):
        h = hash_password("correct horse battery staple")
        assert verify_password("correct horse battery staple", h) is True

    def test_wrong_password_returns_false(self):
        h = hash_password("correct horse battery staple")
        assert verify_password("wrong horse battery staple", h) is False

    def test_case_sensitive(self):
        """bcrypt 是大小写敏感的——大写不同的密码必须判失败。"""
        h = hash_password("Password123")
        assert verify_password("password123", h) is False
        assert verify_password("PASSWORD123", h) is False

    def test_unicode_password_supported(self):
        """中文密码也能 round-trip。"""
        h = hash_password("密码12345")
        assert verify_password("密码12345", h) is True
        assert verify_password("密码12346", h) is False

    def test_hash_is_not_plaintext(self):
        """安全红线:hash 输出绝不应该是明文密码,否则数据库泄露 = 密码泄露。"""
        plaintext = "sup3rSecret!"
        h = hash_password(plaintext)
        assert plaintext not in h
        # 同时不应该和明文逐字符相同
        assert h != plaintext


class TestBcryptAlgorithmContract:
    """跨语言/跨实现的兼容测试:Python 端产出的哈希必须能被同一套 passlib bcrypt
    配置(对应 Java 端 BCryptPasswordEncoder(10))验证。"""

    def test_hash_starts_with_bcrypt_prefix(self):
        """$2b$ / $2a$ 是标准 bcrypt 哈希前缀,Java 端 BCryptPasswordEncoder 也用同样的标识符。"""
        h = hash_password("Password123")
        assert re.match(r"^\$2[abxy]?\$\d{2}\$", h)

    def test_hash_includes_rounds_10(self):
        """rounds 必须与 Java 端 BCryptPasswordEncoder(10) 一致——这保证旧数据兼容。"""
        h = hash_password("Password123")
        # $2b$10$... 的 10 就是 log rounds
        match = re.match(r"^\$2[abxy]?\$(\d{2})\$", h)
        assert match is not None
        assert int(match.group(1)) == 10

    def test_two_hashes_of_same_password_differ(self):
        """bcrypt 每次 salt 不同,两次 hash 不应相等——防止从 hash 反推"密码是否被复用"。"""
        password = "Password123"
        h1 = hash_password(password)
        h2 = hash_password(password)
        assert h1 != h2
        # 但两者都能 verify 通过
        assert verify_password(password, h1) is True
        assert verify_password(password, h2) is True
