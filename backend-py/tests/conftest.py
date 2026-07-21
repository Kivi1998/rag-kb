"""Pytest 全局 conftest。

`app.models.__init__` 已经 eager import 了所有 11 个 ORM model 并按依赖图排序,任何
`import app.models.X` 单独 import 时 SQLAlchemy registry 都已是完整的,字符串式
relationship 全部能解析。早期为了绕开单文件 import 时的 mapper init 顺序而 pre-import
所有 model 的 workaround 已被 __init__.py 取代,这里不再需要重复工作。
"""

from __future__ import annotations
