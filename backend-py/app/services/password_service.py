"""密码哈希服务。对应 Java 版 service/PasswordService.java。

Java 版用 `BCryptPasswordEncoder(10)`——BCrypt,强度(log rounds)10。这里用 passlib 的
bcrypt scheme 保持算法与强度完全一致:两边生成的哈希互相兼容验证,不会导致已有用户
密码校验失败。**这个参数不能随便改**——改了强度或算法,旧密码哈希会验证不通过。

bcrypt 72 字节截断(重要约束,必须告知调用方):
    bcrypt 算法本身只接受最多 **72 字节** 的密码输入,超出部分会被静默截断忽略。
    这与 Java 端 `BCryptPasswordEncoder` 行为完全一致——Java 端也只截断不报错。
    字节数按 UTF-8 计算(`len(password.encode("utf-8"))`),不是字符数:
        - "Password123"             → 11 字节
        - "密码12345"               → 13 字节(每个汉字 3 字节)
        - "a" * 72                   → 72 字节(边界)
        - "a" * 72 + "X"             → 73 字节("X" 永远被忽略)
        - "密码" * 24 + "X"          → 73 字节(最后一个 "X" 被忽略)
    后果:73 字节但仅前 72 字节不同的两个密码,会被 bcrypt 视为同一个密码,产生同一个
    哈希。这意味着:
        1. 实际生效的密码强度上限 = 72 字节,设更长的密码不会增加熵,只是给用户错误印象。
        2. 任意"看起来不同"的超长密码,只要前 72 字节相同,就能 verify 通过对方 hash。
    建议:调用方在用户改密 UI 上提示"密码不超过 72 字节",或在策略层强制截断。
    本服务在 `hash_password` 入口检测到 > 72 字节时会发 `RuntimeWarning`,**不抛**
    ValueError,避免破坏存量 Java 端 hash 库对应的 Python 端改密流程——
    选 warning 而非硬错误是为了在跨语言/跨实现的迁移窗口里保持行为兼容。
    `verify_password` 不在入口加 warning:登录流程不应该因为超长密码而打 WARNING 日志
    干扰告警;verify 阶段只要按同样规则截断就能 match,业务上不会因此出现安全洞。
"""

from __future__ import annotations

import warnings

from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], bcrypt__rounds=10)

_BCRYPT_MAX_BYTES = 72


def _warn_if_too_long(raw_password: str) -> None:
    """bcrypt 静默截断到 72 字节,超出部分被忽略——给调用方发 RuntimeWarning。

    选用 RuntimeWarning(不是 UserWarning)是因为这是"算法行为约束",不是用户输入
    校验错误;调用方在测试里可以通过 `warnings.simplefilter("error", RuntimeWarning)`
    把它转成异常以保证不漏改。
    """
    encoded_len = len(raw_password.encode("utf-8"))
    if encoded_len > _BCRYPT_MAX_BYTES:
        warnings.warn(
            f"密码按 UTF-8 编码后长度为 {encoded_len} 字节,超过 bcrypt 算法的 72 字节上限,"
            f"超出部分({encoded_len - _BCRYPT_MAX_BYTES} 字节)将被静默截断忽略。"
            f"建议在调用方限制密码不超过 72 字节,与 Java 版 BCryptPasswordEncoder 行为一致。",
            RuntimeWarning,
            stacklevel=3,
        )


def hash_password(raw_password: str) -> str:
    """对密码做 bcrypt(10 rounds)哈希,返回标准 `$2b$10$...` 格式。

    警告:超过 72 字节(UTF-8 编码)会被 bcrypt 静默截断——本函数会在入口发
    `RuntimeWarning` 提示,详细说明见模块 docstring。Java 端
    `BCryptPasswordEncoder.encode(rawPassword)` 也是同样的静默截断行为,本次迁移
    故意不抛 ValueError,以保持与 Java 版在迁移窗口期的行为兼容。
    """
    _warn_if_too_long(raw_password)
    return _pwd_context.hash(raw_password)


def verify_password(raw_password: str, password_hash: str) -> bool:
    """校验明文密码与已存 bcrypt 哈希是否匹配。

    警告:超过 72 字节(UTF-8 编码)的密码会被 bcrypt 静默截断后参与匹配——
    与 hash 阶段规则一致,详见模块 docstring。本函数**不**在入口发 warning,
    避免登录/改密校验流程被无关告警污染;只要遵守同样的截断规则,verify 行为
    与 Java 端 `BCryptPasswordEncoder.matches(rawPassword, hashed)` 等价。
    """
    return _pwd_context.verify(raw_password, password_hash)
