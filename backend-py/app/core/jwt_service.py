"""JWT 签发与验证。对应 Java 版 JwtService。

payload:
- sub: userId
- jti: 唯一标识(用于 Redis 黑名单)
- tv:  tokenVersion(用于管理员重置后旧 token 失效)
- exp: 过期时间
"""

import time
import uuid
from dataclasses import dataclass

from jose import JWTError, jwt

from app.core.config import settings

_ALGORITHM = "HS256"
_MINIMUM_HS256_SECRET_BYTES = 32

if not settings.jwt_secret:
    raise RuntimeError("JWT_SECRET 未配置,服务拒绝启动")
if len(settings.jwt_secret.encode("utf-8")) < _MINIMUM_HS256_SECRET_BYTES:
    raise RuntimeError("JWT_SECRET 至少需要 32 个字节")
if settings.jwt_expiration_seconds <= 0:
    raise RuntimeError("JWT_EXPIRATION_SECONDS 必须大于 0")


@dataclass(frozen=True)
class TokenClaims:
    sub: str
    jti: str
    tv: int
    exp: int


def generate_token(user_id: uuid.UUID, token_version: int) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "jti": str(uuid.uuid4()),
        "tv": token_version,
        "iat": now,
        "exp": now + settings.jwt_expiration_seconds,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def parse_token(token: str) -> TokenClaims | None:
    """解析并验证 JWT(签名+有效期)。解析失败返回 None,与 Java 版行为一致。"""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
    except JWTError:
        return None
    tv = payload.get("tv")
    if tv is None:
        tv = -1  # 缺失时必然不匹配任何用户的 tokenVersion(>=0)
    return TokenClaims(sub=payload["sub"], jti=payload["jti"], tv=tv, exp=payload["exp"])


def remaining_seconds(claims: TokenClaims) -> int:
    return max(0, claims.exp - int(time.time()))
