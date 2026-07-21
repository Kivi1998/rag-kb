"""业务异常类。对应 Java 版 exception/ 包下的 6 个异常类。

命名与语义与 Java 版一一对应，供 app.exceptions.handlers 里的 FastAPI 异常处理器映射为
对应 HTTP 状态码(见各类文档字符串里标注的状态码)。
"""


class AccessDeniedException(Exception):
    """同租户内角色权限不足(403)。对应 Java 版 AccessDeniedException。"""


class AccountLockedException(Exception):
    """账号已锁定(423 Locked)。对应 Java 版 AccountLockedException。"""


class BusinessConflictException(Exception):
    """业务不变量冲突(409) —— 如:降级最后一名 owner。对应 Java 版 BusinessConflictException。"""


class ResourceNotFoundException(Exception):
    """资源不存在(404) —— 含跨租户场景:对其他组织资源一律按不存在处理。
    对应 Java 版 ResourceNotFoundException。
    """


class UnauthenticatedException(Exception):
    """未认证(401) —— 请求未携带有效身份凭证。对应 Java 版 UnauthenticatedException。"""
