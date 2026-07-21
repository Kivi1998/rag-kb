"""本地资源与模型缓存目录解析。

对应 RAGFlow 原版 `api/utils/file_utils.get_project_base_directory()`；
本项目直接固定到 `app/deepdoc/res/`，不做 RAGFlow 原版那种多级项目根推导。
"""
from __future__ import annotations

from pathlib import Path

RES_DIR = Path(__file__).resolve().parent / "res"
DEEPDOC_MODEL_DIR = RES_DIR / "deepdoc"


def res_path(*parts: str) -> str:
    RES_DIR.mkdir(parents=True, exist_ok=True)
    return str(RES_DIR.joinpath(*parts))


def deepdoc_model_dir() -> str:
    DEEPDOC_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    return str(DEEPDOC_MODEL_DIR)
