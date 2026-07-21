"""本地资源与模型缓存目录解析。

对应 RAGFlow 原版 `api/utils/file_utils.get_project_base_directory()`；
本项目直接固定到 `app/deepdoc/res/`，不做 RAGFlow 原版那种多级项目根推导。
"""
from __future__ import annotations

from pathlib import Path

RES_DIR = Path(__file__).resolve().parent / "res"
DEEPDOC_MODEL_DIR = RES_DIR / "deepdoc"


def res_path(*parts: str) -> str:
    # 只在目录真的不存在时才 mkdir:生产/验收镜像把 res/ 连同模型文件一起打进
    # 只读根文件系统(见 backend-py/Dockerfile),这种环境下目录早已存在,但
    # `mkdir(exist_ok=True)` 仍然会先尝试底层 mkdir 系统调用——只读文件系统会在
    # 检查"目录是否已存在"之前就直接拒绝这次系统调用,`exist_ok=True` 救不了,
    # 每次调用都会真的抛 `OSError: Read-only file system`。只有目录本身缺失
    # (本地全新开发环境、首次运行)才需要真的创建。
    if not RES_DIR.exists():
        RES_DIR.mkdir(parents=True, exist_ok=True)
    return str(RES_DIR.joinpath(*parts))


def deepdoc_model_dir() -> str:
    if not DEEPDOC_MODEL_DIR.exists():
        DEEPDOC_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    return str(DEEPDOC_MODEL_DIR)
