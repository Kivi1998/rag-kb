"""结构化技术文档切块器。

移植自 Java 版 com.diit.ragkb.ragcore.chunk.impl.TechnicalChunker(508 行),
而 Java 版本身移植自 rag3 项目的 Python chunker.py(MIT License),又在 Java 里做了
扩展(Markdown 标题层级、代码块保护、类/函数定义边界、配置键路径)。本文件是把
已经扩展过的 Java 版忠实翻译回 Python——按 Java 方法逐个对应翻译,保持完全相同的
控制流和切分逻辑。

核心策略(五招式):
1. 在标题、代码围栏、类/函数定义等结构边界处优先下刀
2. 超长块在句子边界二次切分(多级递归降级)
3. overlap 对齐到完整句子,避免半截话
4. 保留 headingPath、pageNo、lineStart/lineEnd、language 等元数据
5. 给每个 chunk 补 sectionPath/contentType/isKeyClause 元数据

许可:rag3 原始算法为 MIT License,本移植文件保留版权声明。

## Java regex → Python re 的关键差异处理

- Java 正则默认 `\\d`/`\\w`/`\\s` 只匹配 ASCII 字符,除非显式开启
  `UNICODE_CHARACTER_CLASS`;Python `re` 对 str 模式默认按 Unicode 匹配这些
  字符类(例如全角数字、全角空白也会被 `\\d`/`\\s` 命中)。Java 源码里没有开启
  该选项,为保持逐字节对齐的匹配语义,这里对用到 `\\d`/`\\w`/`\\s` 的正则统一
  显式传入 `re.ASCII` 标志。
- Java 用内联标志 `(?m)` 直接写在每个 pattern 字符串开头,再把多个已带
  `(?m)` 前缀的 pattern 字符串拼接成 `ALL_BOUNDARIES`;Python 3.11+ 的 `re`
  要求全局内联标志(`(?m)` 不加 `:` 分组限定时)必须出现在整个表达式的最开头,
  拼接后第二、三段的 `(?m)` 会落在字符串中间,直接编译会抛
  `re.PatternError: global flags not at the start of the expression`。这里改为
  用 `re.compile(pattern, re.MULTILINE | re.ASCII)` 的 flags 参数施加
  MULTILINE,pattern 字符串本身不含 `(?m)`,再做字符串拼接就不会触发该限制。
- `ALL_BOUNDARIES`、`CODE_FENCE`、`CODE_DEF` 三个正则在 Java 源码里实际上未被
  任何方法引用(只用于互相拼接),是原始实现里的死代码;为保持逐一对应仍然原样
  移植保留,不做“顺手清理”。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from uuid import UUID

from app.ragcore.chunk.models import Chunk, ChunkingContext, ChunkingOptions, DocumentSection, ParsedDocument

# ── 结构边界正则 ──
# Markdown 标题
MD_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE | re.ASCII)
# 中文结构：第X条、X.、一、（一）
CN_STRUCTURE = re.compile(
    r"^(第[一二三四五六七八九十百零\d]+[条章节])"
    r"|^([一二三四五六七八九十]+[、．.])"
    r"|^([（(][一二三四五六七八九十\d]+[）)])",
    re.MULTILINE | re.ASCII,
)
# 代码围栏(Java 源码中未被引用,仅用于拼 ALL_BOUNDARIES,原样保留)
CODE_FENCE = re.compile(r"^```", re.MULTILINE)
# Java/Python/Go 类/方法/函数定义(Java 源码中未被引用,原样保留)
CODE_DEF = re.compile(
    r"^(public\s+|private\s+|protected\s+)?"
    r"(class|interface|enum|record|def|func|fn|fun|async def)\s+\w+",
    re.MULTILINE | re.ASCII,
)
# 句子边界(注意:Java 源码字符类里 `!`、`?` 各出现两次——ASCII 半角各一次并重复
# 了一遍,并没有包含全角的 ！？——这里逐字符对齐原样保留,不当作笔误“修正”)
SENTENCE_END = re.compile(r"[。!?；!?;\n]")

# 所有结构边界的联合 pattern(Java 源码中未被引用,原样保留)
ALL_BOUNDARIES = re.compile(
    f"{MD_HEADING.pattern}|{CN_STRUCTURE.pattern}|{CODE_FENCE.pattern}",
    re.MULTILINE | re.ASCII,
)

# 单行 code fence 起始/结束行(如 ``` 或 ```python)判定,对应 Java 里内联的
# "^```\\w*$" 字符串正则(Pattern.matches 语义 = 整串匹配,这里用 fullmatch 对应)
_CODE_FENCE_LINE = re.compile(r"```\w*", re.ASCII)

# 按连续空行切分自然段,对应 Java 的 "\n\\s*\n"
_BLANK_LINE_SPLIT = re.compile(r"\n\s*\n", re.ASCII)

# 责任/免责/费率类关键词——命中即标记 isKeyClause=true,供检索侧加权
# (本轮不做检索侧改动,只落地标记本身)。关键词列表后续可按业务扩展。
KEY_CLAUSE_KEYWORDS = frozenset(
    {
        "免除",
        "免责",
        "除外",
        "责任范围",
        "保险责任",
        "赔偿限额",
        "保险金额",
        "费率",
        "违约金",
        "解除合同",
        "终止合同",
    }
)


class HeadingStyle(Enum):
    """一套文档编号风格：由粗到细排列的多级正则,覆盖同一份文档常见的编号写法。

    用于在切分前先扫一遍全文,自动选出命中次数最多的一套风格,而不是对所有文档
    都用同一套死板正则。思路参考 RAGFlow deepdoc 的 bullets_category()(多套候选
    正则 + 统计命中数选优),正则集合与选择逻辑是本项目独立设计实现,不是移植代码。
    """

    # 正式合同/法规常见：第X编/章/节/条，(一)(二)
    # 顺序即层级：编/部分 最粗 → 章 → 节 → 条 → (一)(二),递归降级依赖这个顺序对应真实嵌套深度
    CN_FORMAL = [
        re.compile(r"^第[零一二三四五六七八九十百0-9]+(编|部分)"),
        re.compile(r"^第[零一二三四五六七八九十百0-9]+章"),
        re.compile(r"^第[零一二三四五六七八九十百0-9]+节"),
        re.compile(r"^第[零一二三四五六七八九十百0-9]+条"),
        re.compile(r"^[（(][零一二三四五六七八九十0-9]+[）)]"),
    ]

    # 技术文档/报告常见：第X章/节，1. / 1.1 / 1.1.1
    CN_NUMERIC = [
        re.compile(r"^第[0-9]+章"),
        re.compile(r"^第[0-9]+节"),
        re.compile(r"^[0-9]{1,2}[、.．][^0-9]"),
        re.compile(r"^[0-9]{1,2}\.[0-9]{1,2}(?!\.[0-9])"),
        re.compile(r"^[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,2}"),
    ]

    # 非正式文档常见：第X章/节，一、二、，（一）（1）
    CN_INFORMAL = [
        re.compile(r"^第[零一二三四五六七八九十百0-9]+章"),
        re.compile(r"^第[零一二三四五六七八九十百0-9]+节"),
        re.compile(r"^[一二三四五六七八九十]+[、.]"),
        re.compile(r"^[（(][一二三四五六七八九十]+[）)]"),
        re.compile(r"^[（(][0-9]{1,2}[）)]"),
    ]

    # 英文文档：Part/Chapter/Section/Article
    EN = [
        re.compile(r"(?i)^part (one|two|three|four|five|six|seven|eight|nine|ten)"),
        re.compile(r"(?i)^chapter [ivxlcdm]+"),
        re.compile(r"(?i)^section [0-9]+"),
        re.compile(r"(?i)^article [0-9]+"),
    ]

    def levels(self) -> list[re.Pattern[str]]:
        return self.value

    def level_of(self, line: str) -> int:
        """该行命中的最细级别下标(0 = 最粗);未命中任何级别返回 -1。"""
        stripped = line.strip()
        if not stripped:
            return -1
        for i, pattern in enumerate(self.value):
            if pattern.search(stripped):
                return i
        return -1

    def _count_matches(self, lines: list[str]) -> int:
        return sum(1 for line in lines if self.level_of(line) >= 0)

    @classmethod
    def detect_dominant(cls, lines: list[str], min_hits: int) -> Optional["HeadingStyle"]:
        """扫描全文,返回命中次数最多的风格;如果最高命中数低于 min_hits,说明文档
        没有清晰的编号体系,返回 None,调用方应退化为不强制按结构切分。
        """
        best: Optional["HeadingStyle"] = None
        best_count = 0
        for style in cls:
            count = style._count_matches(lines)
            if count > best_count:
                best = style
                best_count = count
        if best is None or best_count < min_hits:
            return None
        return best


@dataclass(frozen=True)
class _SplitPiece:
    """一个递归降级切分产生的分片,附带该分片末尾有多少字符会作为 overlap 原样
    重复出现在下一个分片的开头。

    只有 _split_by_sentence_with_overlap 这条兜底路径才会产生非零
    overlap_chars——_split_by_level/_split_by_blank_line 产出的分片彼此不重叠
    (原文的不相交切片),overlap_chars 恒为 0。调用方(_chunk_section)据此判断是否
    需要把下一个分片的起始行号往回退,避免把 overlap 重复的内容误当成全新的源
    文件行推进行号。
    """

    text: str
    overlap_chars: int


class TechnicalChunker:
    """结构化技术文档切块器。对应 Java 版 TechnicalChunker,实现 Chunker 接口。"""

    def chunk(self, document: ParsedDocument, context: ChunkingContext, options: ChunkingOptions) -> list[Chunk]:
        chunks: list[Chunk] = []

        all_lines: list[str] = []
        for section in document.sections:
            if section.text is not None:
                all_lines.extend(section.text.split("\n"))
        style = HeadingStyle.detect_dominant(all_lines, 3)

        for section in document.sections:
            section_chunks = self._chunk_section(
                section, document, context.organization_id, context.knowledge_base_id, options, style
            )
            chunks.extend(section_chunks)

        # renumber ordinals globally + 招式 5：链接 prev/next chunk id
        for i, old in enumerate(chunks):
            new_id = _chunk_id(old.document_id, i, old.content)
            metadata = dict(old.metadata)
            metadata.pop("prevChunkId", None)
            metadata.pop("nextChunkId", None)
            chunks[i] = Chunk(
                new_id,
                old.organization_id,
                old.knowledge_base_id,
                old.document_id,
                i,
                old.content,
                old.heading_path,
                old.source_path,
                old.page_no,
                old.line_start,
                old.line_end,
                old.language,
                old.content_hash,
                metadata,
            )

        for i, c in enumerate(chunks):
            metadata = dict(c.metadata)
            if i > 0:
                metadata["prevChunkId"] = chunks[i - 1].id
            if i < len(chunks) - 1:
                metadata["nextChunkId"] = chunks[i + 1].id
            chunks[i] = Chunk(
                c.id,
                c.organization_id,
                c.knowledge_base_id,
                c.document_id,
                c.ordinal,
                c.content,
                c.heading_path,
                c.source_path,
                c.page_no,
                c.line_start,
                c.line_end,
                c.language,
                c.content_hash,
                metadata,
            )

        return chunks

    def _chunk_section(
        self,
        section: DocumentSection,
        document: ParsedDocument,
        org_id: UUID,
        kb_id: UUID,
        options: ChunkingOptions,
        style: Optional[HeadingStyle],
    ) -> list[Chunk]:
        if section.metadata.get("type") == "table":
            return self._chunk_table_section(section, document, org_id, kb_id, options)

        chunks: list[Chunk] = []
        text = section.text
        if text is None or text.strip() == "":
            return chunks

        # Step 1: split into semantic units at structure boundaries
        units = self._split_to_units(text, options)

        # Step 2: fill buffer with units, flush when exceeding maxChars
        buf = ""
        source_line = section.line_start if section.line_start is not None else 1
        buffer_line_start = source_line
        current_line = source_line

        for unit in units:
            unit_lines = _count_lines(unit)
            if self._starts_structural_unit(unit) and buf != "":
                chunks.append(
                    self._flush_buffer(
                        buf, section, document, org_id, kb_id, len(chunks), buffer_line_start, current_line - 1
                    )
                )
                buf = ""
                buffer_line_start = current_line

            is_code_fence_line = options.preserve_code_blocks and bool(
                _CODE_FENCE_LINE.fullmatch(unit.strip())
            )

            # code fence toggle: always accumulate (code blocks kept together)
            if is_code_fence_line or (
                options.preserve_code_blocks and len(buf) > 0 and buf.strip().startswith("```")
            ):
                if buf != "":
                    buf += "\n"
                buf += unit
                current_line += unit_lines
                continue

            # check if adding unit exceeds max
            if buf != "" and len(buf) + len(unit) > options.max_characters:
                prev = buf
                chunks.append(
                    self._flush_buffer(
                        buf, section, document, org_id, kb_id, len(chunks), buffer_line_start, current_line - 1
                    )
                )
                buf = ""

                # carry overlap from previous block tail
                overlap = _tail_overlap(prev, options.overlap_characters)
                if overlap != "":
                    buf += overlap
                    buffer_line_start = max(
                        section.line_start if section.line_start is not None else 1,
                        current_line - _count_lines(overlap),
                    )
                else:
                    buffer_line_start = current_line

            if buf != "":
                buf += "\n"
            buf += unit
            current_line += unit_lines

            # if single unit alone exceeds max, recursively split at finer structure,
            # then paragraph, then sentence boundaries (招式 2：多级递归降级)
            if len(buf) > options.max_characters:
                overlong = buf
                buf = ""
                first_line = overlong.split("\n", 1)[0]
                unit_level = style.level_of(first_line) if style is not None else -1
                for piece in self._recursive_split(overlong, style, unit_level, options):
                    piece_line_end = buffer_line_start + _count_lines(piece.text) - 1
                    chunks.append(
                        self._flush_buffer(
                            piece.text,
                            section,
                            document,
                            org_id,
                            kb_id,
                            len(chunks),
                            buffer_line_start,
                            piece_line_end,
                        )
                    )
                    # 下一个 piece 的起始行号：若当前 piece 末尾带有 overlap(会被下一个
                    # piece 的开头原样重复),需要把 buffer_line_start 往回退 overlap 对应
                    # 的行数——因为 overlap 内容是同一批源文件行,不应该被当成全新的行推进。
                    if piece.overlap_chars <= 0:
                        buffer_line_start = piece_line_end + 1
                    else:
                        overlap_tail = piece.text[-piece.overlap_chars :]
                        buffer_line_start = max(
                            section.line_start if section.line_start is not None else 1,
                            piece_line_end - _count_lines(overlap_tail) + 1,
                        )
                current_line = buffer_line_start

        # flush remaining
        if buf != "":
            chunks.append(
                self._flush_buffer(
                    buf, section, document, org_id, kb_id, len(chunks), buffer_line_start, current_line - 1
                )
            )

        return chunks

    def _chunk_table_section(
        self,
        section: DocumentSection,
        document: ParsedDocument,
        org_id: UUID,
        kb_id: UUID,
        options: ChunkingOptions,
    ) -> list[Chunk]:
        """表格分块：小表格整体保留为一个 chunk；超出 maxCharacters 的大表格按行
        分组,每组前面都重新带上表头行,避免"模型只看到中间几行、不知道每列是
        什么"(招式 3)。
        """
        text = section.text.strip()
        if len(text) <= options.max_characters:
            return [
                self._flush_buffer(
                    text,
                    section,
                    document,
                    org_id,
                    kb_id,
                    0,
                    section.line_start if section.line_start is not None else 1,
                    section.line_end if section.line_end is not None else 1,
                )
            ]

        lines = text.split("\n")
        header_line = lines[0]
        chunks: list[Chunk] = []
        group = header_line
        group_start_line = (section.line_start if section.line_start is not None else 1) + 1
        current_line = group_start_line

        for row in lines[1:]:
            if row.strip() == "":
                continue
            candidate = group + "\n" + row
            if len(candidate) > options.max_characters and len(group) > len(header_line):
                chunks.append(
                    self._flush_buffer(
                        group, section, document, org_id, kb_id, len(chunks), group_start_line, current_line - 1
                    )
                )
                group = header_line
                group_start_line = current_line
            group += "\n" + row
            current_line += 1

        if len(group) > len(header_line):
            chunks.append(
                self._flush_buffer(
                    group, section, document, org_id, kb_id, len(chunks), group_start_line, current_line - 1
                )
            )

        # 兜底：如果表格没有任何数据行(或所有数据行都是空白被跳过),主循环一次都
        # 不会 flush,chunks 会是空列表——整张表就此从输出里静默消失。这里保证哪怕
        # 只有一个超长表头,也至少产出一个包含表头的 chunk。
        if not chunks:
            fallback_line = section.line_start if section.line_start is not None else 1
            chunks.append(
                self._flush_buffer(
                    header_line, section, document, org_id, kb_id, 0, fallback_line, fallback_line
                )
            )
        return chunks

    def _split_to_units(self, text: str, options: ChunkingOptions) -> list[str]:
        """Split text at natural structure boundaries. Overlong units are split in
        _chunk_section so that options.max_characters is the only length limit.
        """
        units: list[str] = []

        lines = text.split("\n")
        current = ""
        in_code_fence = False
        preserve_code = options.preserve_code_blocks

        for line in lines:
            stripped = line.strip()

            # code fence toggle — only if preserveCodeBlocks is enabled
            if preserve_code and _CODE_FENCE_LINE.fullmatch(stripped):
                if in_code_fence:
                    current += line + "\n"
                    units.append(current.strip())
                    current = ""
                    in_code_fence = False
                else:
                    current = _flush_current(current, units)
                    current += line + "\n"
                    in_code_fence = True
                continue

            # inside code fence: accumulate everything
            if in_code_fence:
                current += line + "\n"
                continue

            # markdown heading: new semantic unit
            if MD_HEADING.search(line):
                current = _flush_current(current, units)
                current += line + "\n"
                continue

            # Chinese structure heading
            if stripped != "" and CN_STRUCTURE.search(stripped):
                current = _flush_current(current, units)
                current += line + "\n"
                continue

            # blank line: paragraph boundary
            if line.strip() == "":
                if len(current) > 50:
                    current = _flush_current(current, units)
                    current = ""
                elif current != "":
                    current += "\n"
                continue

            current += line + "\n"

        _flush_current(current, units)
        return units

    def _starts_structural_unit(self, unit: str) -> bool:
        stripped = unit.strip()
        return bool(MD_HEADING.search(stripped)) or bool(CN_STRUCTURE.search(stripped))

    def _recursive_split(
        self, unit: str, style: Optional[HeadingStyle], level: int, options: ChunkingOptions
    ) -> list[_SplitPiece]:
        """递归地把一个过长的文本单元按"更细一级编号 → 空行分段 → 句子边界"逐级
        降级切分,每一级都优先保住更大的语义单元,装不下才继续往下降级。
        """
        if len(unit) <= options.max_characters:
            return [_SplitPiece(unit, 0)]

        if style is not None and level + 1 < len(style.levels()):
            finer = self._split_by_level(unit, style, level + 1)
            if len(finer) > 1:
                result: list[_SplitPiece] = []
                for piece in finer:
                    result.extend(self._recursive_split(piece, style, level + 1, options))
                return result

        paragraphs = _split_by_blank_line(unit)
        if len(paragraphs) > 1:
            result = []
            for p in paragraphs:
                result.extend(self._recursive_split(p, style, level, options))
            return result

        return _split_by_sentence_with_overlap(unit, options)

    def _split_by_level(self, text: str, style: HeadingStyle, level: int) -> list[str]:
        """按某个编号级别的正则,在行边界处把文本切成若干段(每段以命中该级别的行开头)。"""
        lines = text.split("\n")
        pieces: list[str] = []
        current = ""
        for line in lines:
            if style.level_of(line) == level and current != "":
                pieces.append(current.strip())
                current = ""
            current += line + "\n"
        if current != "":
            pieces.append(current.strip())
        return [s for s in pieces if s != ""]

    def _flush_buffer(
        self,
        content: str,
        section: DocumentSection,
        document: ParsedDocument,
        org_id: UUID,
        kb_id: UUID,
        ordinal: int,
        line_start: int,
        line_end: int,
    ) -> Chunk:
        lang = document.metadata.get("language", "")
        chunk_id_value = _chunk_id(document.document_id, ordinal, content)
        enriched_metadata = _enrich_metadata(section, content)

        return Chunk(
            chunk_id_value,
            org_id,
            kb_id,
            document.document_id,
            ordinal,
            content,
            section.heading_path,
            document.source_path,
            section.page_no,
            None if section.line_start is None else line_start,
            None if section.line_end is None else line_end,
            lang,
            _sha256_8(content),
            enriched_metadata,
        )


def _flush_current(buf: str, units: list[str]) -> str:
    s = buf.strip()
    if s != "":
        units.append(s)
    return ""


def _tail_overlap(text: str, overlap: int) -> str:
    """Take tail of text up to overlap chars, aligned to sentence boundary.
    Ported from rag3 _tail_overlap.
    """
    if overlap <= 0 or len(text) <= overlap:
        return ""
    tail = text[-overlap:]
    m = SENTENCE_END.search(tail)
    if m:
        idx = m.end()
        if idx < len(tail):
            return tail[idx:]
    return ""


def _find_sentence_split(text: str, max_chars: int) -> int:
    """Find the best position to split text at or before maxChars, aligned to a sentence boundary."""
    slice_ = text[: min(max_chars, len(text))]
    last_end = max_chars
    for m in SENTENCE_END.finditer(slice_):
        last_end = m.end()
    return last_end


def _split_by_blank_line(text: str) -> list[str]:
    """按连续空行把文本切成自然段。"""
    return [s.strip() for s in _BLANK_LINE_SPLIT.split(text) if s.strip() != ""]


def _split_by_sentence_with_overlap(text: str, options: ChunkingOptions) -> list[_SplitPiece]:
    """最后一级降级：按句子边界切分,沿用已有的 find_sentence_split + tail_overlap。"""
    pieces: list[_SplitPiece] = []
    remaining = text
    while len(remaining) > options.max_characters:
        split_at = _find_sentence_split(remaining, options.max_characters)
        head = remaining[:split_at]
        overlap = _tail_overlap(head, options.overlap_characters)
        pieces.append(_SplitPiece(head, len(overlap)))
        tail = remaining[split_at:]
        remaining = tail if overlap == "" else overlap + tail
    if remaining != "":
        pieces.append(_SplitPiece(remaining, 0))
    return pieces


def _enrich_metadata(section: DocumentSection, content: str) -> dict[str, str]:
    """招式 5：给每个 chunk 补 sectionPath / contentType / isKeyClause 元数据。"""
    metadata = dict(section.metadata)
    if section.heading_path:
        metadata["sectionPath"] = " > ".join(section.heading_path)
    metadata["contentType"] = section.metadata.get("type", "text")
    is_key_clause = any(keyword in content for keyword in KEY_CLAUSE_KEYWORDS)
    metadata["isKeyClause"] = "true" if is_key_clause else "false"
    return metadata


def _count_lines(text: Optional[str]) -> int:
    if text is None or text == "":
        return 0
    return text.count("\n") + 1


def _sha256_8(input_text: str) -> str:
    return hashlib.sha256(input_text.encode("utf-8")).hexdigest()[:8]


def _chunk_id(document_id: UUID, ordinal: int, content: str) -> str:
    return f"{document_id}:{ordinal}:{_sha256_8(content)}"
