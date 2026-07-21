"""语音转写(ASR)能力 —— 从 `parser-gateway/app/parsers.py` 移植的 faster-whisper 封装。

背景:parser-gateway 最初被拆成独立 HTTP 微服务,是因为主编排后端历史上是 Java,Java 没有
好用的 OCR/ASR 生态,只能通过 HTTP 调用一个 Python 微服务。现在主后端(backend-py)本身
也是 Python 了,ASR 能力直接下沉为内部模块调用,不再需要跨进程 HTTP 往返。

**范围说明**:本模块只完成"能力搬运"(模型加载 + 转写 + 产出统一的 `DocumentSection` 序列),
尚未接入现有解析流水线——`factory.py` 如何在 `DocumentParser`/`MultimodalDocumentParser`
体系里挂载这个模块,是后续任务,不在本模块职责范围内。

异常层级说明(与 `app.ragcore.model.NeedsMultimodalParsingException` 的关系):
- `NeedsMultimodalParsingException` 是"移交决策"层面的异常——由 docx_parser.py /
  pdf_parser.py / pptx_parser.py 等*本地格式*解析器在判断"这份文档必须用 OCR/ASR 才能
  继续解析"时抛出,语义是"请上层换用多模态网关/多模态实现处理",与具体某个多模态实现
  (OCR 还是 ASR、用什么模型)无关。
- 本模块的 `ParseError` / `ParserUnavailableError` 是"执行"层面的异常——描述 ASR 这个具体
  多模态实现自身在真正尝试转写时的失败(运行时未安装、模型加载失败、转写没有产出任何
  文本等),语义类似 docx_parser.py 内部可能抛出的 ValueError/IOError,而不是
  `NeedsMultimodalParsingException` 那种"移交"信号。
- 两者不是同一层级的概念,因此不应合并:backend-py 目前没有面向"多模态实现内部失败"的
  等价异常类,故在本模块新增定义。未来把 ASR 接入 `MultimodalDocumentParser` 时,调用方
  应该 catch 这两个异常并按需要转换语义(例如包装为面向用户的错误提示),而不是让它们
  被误当成 `NeedsMultimodalParsingException` 处理。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.ragcore.model import DocumentSection

logger = logging.getLogger(__name__)


class ParseError(RuntimeError):
    """ASR 转写执行失败(如未产生任何文本片段)。"""


class ParserUnavailableError(RuntimeError):
    """ASR 运行时未安装,或模型加载失败,导致转写能力当前不可用。"""


# 模型只加载一次、且加载/推理过程线程安全:用同一把锁同时保护"惰性初始化"和"调用推理"两段
# 临界区(与 parser-gateway 原实现语义一致)——faster-whisper 的 WhisperModel 实例不保证支持
# 并发 transcribe() 调用,序列化推理调用比引入每请求一个模型实例的开销更划算。
_whisper_lock = threading.Lock()
_whisper_model: Any = None


def ensure_asr_ready() -> str:
    """确保 faster-whisper 模型已加载完成,返回当前生效的模型名。

    线程安全:并发调用只会触发一次真正的模型加载(双重检查锁),后续调用直接复用已加载的
    模型实例。运行时缺失或模型加载失败时抛出可识别的 `ParserUnavailableError`,方便调用方
    fail-fast 而不是让底层库的原始异常裸露出去。
    """
    global _whisper_model

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise ParserUnavailableError("ASR 运行时未安装(缺少 faster-whisper 依赖)") from exc

    with _whisper_lock:
        if _whisper_model is None:
            model_name = settings.rag_whisper_model
            device = settings.rag_whisper_device
            compute_type = settings.rag_whisper_compute_type
            try:
                _whisper_model = WhisperModel(model_name, device=device, compute_type=compute_type)
            except Exception as exc:  # noqa: BLE001 - 需要把底层任意加载失败统一收敛为可识别异常
                raise ParserUnavailableError(f"ASR 模型不可用: {model_name}") from exc
        return settings.rag_whisper_model


def asr_is_loaded() -> bool:
    """模型是否已经加载完成(供健康检查/延迟初始化探测使用,不触发加载)。"""
    return _whisper_model is not None


@dataclass(frozen=True)
class AsrTranscript:
    """一次媒体文件转写的结果:按字幕切分的 `DocumentSection` 序列 + 顶层元数据。

    对应 parser-gateway `_parse_media()` 原先返回的
    `{"sections": [...], "metadata": {...}}` 字典结构,这里用本项目既有的
    `DocumentSection`(`app.ragcore.model`)代替裸字典,字段一一对应
    (`text`/`heading_path`/`page_no`/`line_start`/`line_end`/`metadata`),
    保持与 docx_parser.py 等其他解析器同一套领域模型。
    """

    sections: tuple[DocumentSection, ...] = field(default_factory=tuple)
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sections", tuple(self.sections or ()))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))


def transcribe_media(path: Path) -> AsrTranscript:
    """对本地磁盘上的音频/视频文件做语音转写,按字幕分段产出 `AsrTranscript`。

    没有可用文本片段时抛出 `ParseError`(与 parser-gateway 原实现一致的 fail-fast 语义)。
    """
    ensure_asr_ready()
    with _whisper_lock:
        segments, info = _whisper_model.transcribe(str(path), vad_filter=True)
        sections = tuple(
            _section(
                segment.text.strip(),
                metadata={
                    "type": "subtitle",
                    "timeRange": f"{_timestamp(segment.start)} --> {_timestamp(segment.end)}",
                    "startSeconds": f"{segment.start:.3f}",
                    "endSeconds": f"{segment.end:.3f}",
                },
            )
            for segment in segments
            if segment.text.strip()
        )
    if not sections:
        raise ParseError("ASR 未产生任何转写文本")
    return AsrTranscript(
        sections=sections,
        metadata={
            "format": path.suffix.lower().lstrip("."),
            "language": str(info.language),
            "segmentCount": str(len(sections)),
        },
    )


def _section(text: str, metadata: dict[str, str] | None = None) -> DocumentSection:
    return DocumentSection(text=text, metadata=metadata or {})


def _timestamp(seconds: float) -> str:
    total_ms = int(seconds * 1000)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"
