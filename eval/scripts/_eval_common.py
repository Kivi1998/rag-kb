"""eval/scripts/ 下几个真实回归/复现工具共用的引导逻辑与常量。

背景：`eval_corpus_indexer.py` / `eval_retrieval_runner.py` /
`eval_fact_verification_runner.py` / `eval_answer_self_checker_runner.py` 这 4 个脚本
是从已删除的 Java 工具（`EvalCorpusIndexer.java` 等）移植过来的，均需要 import
`backend-py/app/ragcore/` 下的生产类，并共享同一套评测租户常量。抽成本模块避免
4 个脚本各自复制一份。

## sys.path / cwd 约定

`eval/` 与 `backend-py/` 是仓库根目录下两个独立顶层目录，没有天然的 Python 包关系；
同时 `app.core.config.Settings` 用 `env_file=".env"`（相对路径）加载
`backend-py/.env`，这个相对路径是相对进程 cwd 解析的，不是相对模块文件。

因此本模块提供 `bootstrap_backend_py()`：
1. 把 `backend-py/` 加入 `sys.path`，使 `import app.xxx` 可用；
2. 把进程 cwd 切到 `backend-py/`，使 `Settings()` 能找到 `backend-py/.env`；
3. 用 `python-dotenv` 把 `backend-py/.env` 显式加载进 `os.environ`。

第 3 点是必需的，不是多余的保险：4 个脚本里 `RAG_EMBEDDING_ENDPOINT`/
`RAG_RERANK_ENDPOINT`/`RAG_GENERATION_ENDPOINT` 等环境变量读取，都是直接
`os.environ.get(...)`（对应 Java 版 `System.getenv(...)` 的语义——只认真实进程
环境变量，不认 pydantic Settings 内部解析出的值）。而 `app.core.config.Settings`
用 `SettingsConfigDict(env_file=".env")` 加载配置时，只是把 `.env` 的键值喂给
**这一个 Settings 实例**，并不会把它们写回 `os.environ`——单纯 `import
app.core.config` 不会让 `os.environ.get("RAG_RERANK_ENDPOINT")` 出现值。
`backend-py/.env` 里部分取值本身含 `&` 等 shell 特殊字符（如
`RAG_MEMORY_MONGO_URI` 的查询串），直接 `source .env` 到 bash 里会解析报错，
所以也不能简单指望调用方已经手动 `set -a && source backend-py/.env && set +a`
——用 `python-dotenv`（`pydantic-settings` 本身的依赖，无需额外安装）加载，
不依赖 shell 语法，行为在任意调用方式下都确定一致。

**调用约定**：4 个脚本的 `main()` 必须先用 `argparse` 拿到的路径参数调用
`.resolve()` 转成绝对路径，再调用 `bootstrap_backend_py()`，最后才 import 任何
`app.*` 模块——顺序反了的话，相对路径参数会在 chdir 后指向错误位置。这样脚本可以
在任意 cwd 下用 `python3 eval/scripts/xxx.py ...` 直接运行，不需要用户自己记得
先 `cd backend-py` 或手动 source `.env`。
"""

from __future__ import annotations

import hashlib
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
BACKEND_PY_DIR = REPO_ROOT / "backend-py"


def bootstrap_backend_py() -> None:
    """把 backend-py 加入 sys.path、cwd 切过去、并加载 backend-py/.env 到 os.environ。

    必须在 import 任何 app.* 模块前调用一次。
    """
    backend_py_str = str(BACKEND_PY_DIR)
    if backend_py_str not in sys.path:
        sys.path.insert(0, backend_py_str)
    os.chdir(BACKEND_PY_DIR)
    # override=False：真实 shell 环境变量（如果调用方确实手动 export 过）优先于 .env 文件，
    # 与 pydantic-settings 对 env_file 的优先级语义保持一致。
    load_dotenv(BACKEND_PY_DIR / ".env", override=False)


def java_name_uuid_from_bytes(data: bytes) -> uuid.UUID:
    """等价于 Java `UUID.nameUUIDFromBytes(byte[])`。

    Java 该方法直接对输入字节数组算 MD5，再把版本/变体位改写成 3 / RFC4122，
    **不像**标准 UUID v3 那样先拼接一个 namespace UUID 前缀。Python 标准库
    `uuid.uuid3(namespace, name)` 强制要求 namespace，与 Java 算法不等价（会得到
    不同的 UUID），因此这里手写复刻 Java 的具体算法，保证跨脚本共享的常量 UUID
    （如 `EVAL_ORG_ID`/`EVAL_KB_ID`）、以及按文件名派生的 document_id 在同一批
    脚本内保持确定性（同一输入 → 同一 UUID）。
    """
    digest = bytearray(hashlib.md5(data).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30  # version 3
    digest[8] = (digest[8] & 0x3F) | 0x80  # variant RFC4122
    return uuid.UUID(bytes=bytes(digest))


# EvalRetrievalRunner / EvalFactVerificationRunner 共用的评测租户常量。
# 对应 Java `UUID.nameUUIDFromBytes("org-bdzdc".getBytes(StandardCharsets.UTF_8))`
# 与 `UUID.nameUUIDFromBytes("kb-bdzdc".getBytes(StandardCharsets.UTF_8))`。
EVAL_ORG_ID: uuid.UUID = java_name_uuid_from_bytes(b"org-bdzdc")
EVAL_KB_ID: uuid.UUID = java_name_uuid_from_bytes(b"kb-bdzdc")

# 两个脚本共用的独立评测索引名（不触碰生产 rag_chunks_v1）。
EVAL_INDEX_NAME: str = "rag_chunks_eval_v3"

# 评测索引使用的向量维度（bge-m3 模型输出维度），对应 Java 版 `VECTOR_DIMS`。
EVAL_VECTOR_DIMS: int = 1024


def parse_bool(value: str | None) -> bool:
    """对应 Java `Boolean.parseBoolean(String)`：大小写不敏感地匹配 "true"，其余一律 false。"""
    return (value or "").strip().lower() == "true"
