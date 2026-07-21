"""SRT / WebVTT 字幕解析器。对应 SubtitleParser.java。

保留时间轴用于问答引用定位:每条字幕存为独立 `DocumentSection`,text 是字幕
文本本身(不含时间戳),metadata 携带 `start` / `end` / `timeRange` / `index` 四个
时间轴字段,引用定位可以回到毫秒级。

**正则容错**:
- 时间戳分隔符同时接受 `,`(SRT 毫秒)和 `.`(VTT 毫秒),两种都能匹配。
- WEBVTT 头(含可选的 `WEBVTT - description` 之类说明行)整行丢弃。
- SRT 编号行(纯数字)被当作 cue 索引,不再被错误拼进字幕文本——索引值
  写进 `metadata["index"]`,若该 cue 没有可识别的纯数字索引,index 字段
  仍写入但值是 cue 在文件内的顺序(从 1 开始)。
- 一个空行作为 cue 分隔;缺时间行或时间行后无文本的 block 静默丢弃。
"""

from __future__ import annotations

import re

from app.ragcore.models import DocumentInput, DocumentSection, ParsedDocument
from app.ragcore.parser._util import extension_of
from app.ragcore.parser.base import DocumentParser

_SUPPORTED_TYPES = {
    "application/x-subrip",
    "text/vtt",
    "text/srt",
    "text/plain",  # 兼容一些前端不传具体 subtype 的情况
}
_SUBTITLE_EXTENSIONS = {"srt", "vtt"}

# 匹配 "HH:MM:SS,mmm --> HH:MM:SS,mmm" 或 "HH:MM:SS.mmm --> HH:MM:SS.mmm"
# 或更紧凑的 "MM:SS.mmm --> MM:SS.mmm"（不强制 HH 段）
_TIME_LINE_RE = re.compile(
    r"\s*"
    r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3}|\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})"
    r"\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3}|\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})"
    r"[^,\n]*"  # 允许 VTT 的 cue settings（line/position/align 等）跟在后面
    r"\s*"
)
_PURE_NUMBER_RE = re.compile(r"^\d+$")


class SubtitleParser(DocumentParser):
    def supports(self, content_type: str | None, filename: str | None) -> bool:
        if content_type and content_type.lower() in _SUPPORTED_TYPES:
            # 只在文件名也是字幕扩展名时才报"是字幕"——避免 text/plain 误吃全部 .txt/.md
            if filename and extension_of(filename) in _SUBTITLE_EXTENSIONS:
                return True
            # 没文件名 / 文件名不是字幕扩展名时,text/plain 不能盲目认
            if filename is None:
                return content_type is not None and content_type.lower() in {
                    "application/x-subrip", "text/vtt", "text/srt"
                }
            return False
        if filename:
            return extension_of(filename) in _SUBTITLE_EXTENSIONS
        return False

    def parse(self, document_input: DocumentInput) -> ParsedDocument:
        stream = document_input.open_stream()
        try:
            raw = stream.read().decode("utf-8", errors="replace")
        finally:
            stream.close()

        all_lines = raw.splitlines()
        sections: list[DocumentSection] = []

        current_block: list[tuple[int, str]] = []  # (line_no_1based, line_text)
        block_start: int | None = None
        # SRT 文件可能有的纯数字编号行(如 "1\n00:00:01,000 --> ...")的暂存
        _pending_index: str | None = None
        # cue 序号:VTT 没有显式编号,这里按出现顺序递增(从 1 开始),
        # 与 SRT 文件的显式编号对齐——这样下游引用方不需要关心是 SRT 还是 VTT。
        cue_ordinal = 0

        def flush(end_line: int, explicit_index: str | None) -> None:
            nonlocal current_block, block_start, cue_ordinal
            if block_start is None or not current_block:
                block_start = None
                current_block = []
                return
            time_match: re.Match[str] | None = None
            time_index = -1
            for idx, (_, text) in enumerate(current_block):
                if _TIME_LINE_RE.match(text):
                    time_match = _TIME_LINE_RE.match(text)
                    time_index = idx
                    break
            if time_match is None or time_index == len(current_block) - 1:
                # 没有时间行,或时间行后没有文本 → 整块丢弃
                block_start = None
                current_block = []
                return
            start_ts = _normalize_ts(time_match.group("start"))
            end_ts = _normalize_ts(time_match.group("end"))
            time_range = f"{start_ts} --> {end_ts}"
            text_lines = [t for _, t in current_block[time_index + 1 :]]
            cue_text = "\n".join(text_lines).strip()
            if cue_text:
                # line_start 是 cue 文本的起始行(也就是时间行的下一行);
                # line_end 是当前 flush 触发位置的上一行(空行分隔符前面那一行)
                cue_start = current_block[time_index + 1][0]
                cue_end = end_line - 1  # end_line 已经是下一空行的行号(1-based),回退一格
                if cue_end < cue_start:
                    cue_end = cue_start
                cue_ordinal += 1
                # 优先用 SRT 显式编号;VTT 没有,fallback 到按出现顺序递增的 ordinal。
                index_value = explicit_index if explicit_index is not None else str(cue_ordinal)
                sections.append(DocumentSection(
                    text=cue_text,
                    heading_path=("字幕",),
                    page_no=None,
                    line_start=cue_start,
                    line_end=cue_end,
                    metadata={
                        "type": "subtitle",
                        "timeRange": time_range,
                        "start": start_ts,
                        "end": end_ts,
                        "index": index_value,
                    },
                ))
            block_start = None
            current_block = []

        for i, line in enumerate(all_lines):
            line_no = i + 1
            stripped = line.strip()
            if not stripped:
                # 空行:段落分隔
                if block_start is not None:
                    flush(line_no, _pending_index)
                    _pending_index = None
                continue
            # 丢弃 WEBVTT 头(包括 "WEBVTT", "WEBVTT - desc", "WEBVTT\t..." 之类)
            if stripped.upper().startswith("WEBVTT"):
                continue
            # SRT 编号行(纯数字)→ 作为 cue 索引记下,在 flush 时写入 metadata
            if _PURE_NUMBER_RE.match(stripped):
                if block_start is None:
                    block_start = line_no
                _pending_index = stripped
                current_block.append((line_no, stripped))
                continue
            if block_start is None:
                block_start = line_no
            current_block.append((line_no, stripped))
        # 末尾兜底
        if block_start is not None and current_block:
            flush(len(all_lines) + 1, _pending_index)

        if not sections:
            raise IOError("字幕文件中没有可索引的字幕内容")

        # 区分 vtt / srt
        fmt = "vtt" if (document_input.filename() and extension_of(document_input.filename()) == "vtt") else "srt"
        return ParsedDocument(
            document_id=document_input.document_id(),
            content_type=document_input.content_type(),
            source_path=document_input.source_path(),
            sections=tuple(sections),
            metadata={
                "format": fmt,
                "cueCount": str(len(sections)),
                "filename": document_input.filename() or "",
            },
        )


def _normalize_ts(raw: str) -> str:
    """把 SRT `,` 毫秒分隔统一成 VTT `.` 风格,缺 HH 段补成 `HH:MM:SS.mmm` 以便引用稳定。"""
    if "," in raw:
        raw = raw.replace(",", ".")
    parts = raw.split(":")
    if len(parts) == 2:
        # MM:SS.mmm → HH:MM:SS.mmm
        raw = f"00:{raw}"
    # 秒段补零到 2 位(已经保证 . 后 3 位毫秒)
    h, m, s = raw.split(":")
    s_fixed = s.zfill(5) if len(s.split(".")[0]) < 2 else s
    return f"{int(h):02d}:{int(m):02d}:{s_fixed}"
