"""拦截生成流首行的事实核验判断,补上 rerank 阈值覆盖不到的 NO_RETRIEVAL 类拒答盲区。

对应 Java 版 `ragcore/generation/FactVerificationGate.java`。`AnswerGenerator` 在 System
Prompt 里要求模型先输出一行 `{"found": true|false}` 判断检索结果是否包含问题的具体答案,
本类负责在流式输出的最前面拦截这一行做判定:

- `found:true` → 模式切到 `PASSTHROUGH`,先补发被延迟的 `SOURCE` 引用事件再原样转发后续
  chunk,把"已展示引用又拒答"这种自相矛盾挡住;
- `found:false` → 模式切到 `REFUSED`,只发一条固定拒答话术的 `REFUSAL` 事件,丢弃已缓冲
  内容与后续任何输出,避免模型在不该给正文的时候输出正文;
- 缓冲超过 200 字符仍解析不出合法判断时 `fail-open`:把已缓冲内容当正文透传,退化为本机制
  关闭前的行为,不引入新的拒答误伤。

**调用方必须在流结束后调用 `flush()`** —— 模型整段输出可能就是判断行本身(无换行、也不到
200 字符),不在 `flush()` 里补一次解析,内容会永远卡在缓冲区里、既不拒答也不透传。

Python 版相比 Java 的差异:Java 用 `Consumer<QueryEvent>` 回调把事件推给下游,本类沿用
同一思路但把下游接口从 `Consumer` 改为 `feed(event) -> list[QueryEvent]` + `flush()`:
调用方在 async generator 循环里把上游事件 `feed` 给本类、收集返回的下游事件一起 `yield`。
这种 pull-based 写法对 async generator 自然,显式的 `flush()` 也比 Java 版依赖消费者主动
调 `flush()` 难漏。
"""

from __future__ import annotations

import json
from enum import Enum

from app.ragcore.model import Citation, QueryEvent

# 缓冲超过这个字符数仍解析不出合法判断时,放弃解析直接透传。Java 版同款常量。
MAX_BUFFER_CHARS = 200

# `found:false` 时的固定拒答话术。Java 版同款常量,文案原样保留。
FIXED_REFUSAL_MESSAGE = "未在当前知识库中检索到该问题的具体答案"


class _Mode(str, Enum):
    """内部状态机:首行解析前在 BUFFERING,找到 found:true 后切 PASSTHROUGH,found:false 切 REFUSED。"""

    BUFFERING = "buffering"
    PASSTHROUGH = "passthrough"
    REFUSED = "refused"


class FactVerificationGate:
    """事实核验流式拦截器。详见模块 docstring。"""

    def __init__(self, citations: list[Citation]) -> None:
        # 引用列表在 found:true 时才补发,避免"已展示引用又拒答"的自相矛盾。允许 None/
        # 不可迭代输入被归一化处理。
        self._citations: tuple[Citation, ...] = tuple(citations or ())
        self._buffer: str = ""
        self._mode: _Mode = _Mode.BUFFERING
        self._refused: bool = False

    @property
    def refused_by_fact_verification(self) -> bool:
        """流结束后调用方据此把审计状态记为 REFUSED 而非 COMPLETED。对应 Java 同名 getter。"""
        return self._refused

    def feed(self, event: QueryEvent) -> list[QueryEvent]:
        """推入一个上游事件,返回应当推送给下游的事件列表(0 或 1 个)。

        行为分三态:
        - 已 PASSTHROUGH: 原样转发
        - 已 REFUSED: 丢弃上游事件,返回空
        - BUFFERING 中: 把 `content` 追加进缓冲区,见换行或缓冲满 200 字符时一次性
          解析首行判定模式
        """
        if self._mode is _Mode.PASSTHROUGH:
            return [event]
        if self._mode is _Mode.REFUSED:
            return []
        # BUFFERING:仅把 CHUNK 的 content 拼入缓冲区;其他事件(SOURCE/REFUSAL 等)
        # 直接转发,避免引用/错误事件被卡住。SOURCE 走这里转发属于"已展示引用又拒答"
        # 的边界场景,但 Java 版同样如此,这里保持一致。
        if event.content is None:
            return [event]
        self._buffer += event.content
        newline_index = self._index_of_newline(self._buffer)
        if newline_index >= 0:
            return self._resolve_first_line(newline_index)
        if len(self._buffer) >= MAX_BUFFER_CHARS:
            return self._fail_open()
        return []

    def flush(self) -> list[QueryEvent]:
        """流结束后必须调用。对仍处于 BUFFERING 状态的剩余内容做收尾解析。

        常见于模型整段输出就是判断行本身(无换行、也不到 200 字符),不在 `flush()` 补一次
        解析,内容会永远卡在缓冲区里、既不拒答也不透传。Java 版同款契约。
        """
        if self._mode is not _Mode.BUFFERING:
            return []
        if not self._buffer:
            # 模型完全没产出内容(理论不应发生):切 PASSTHROUGH 补发引用、然后让下游走完。
            self._mode = _Mode.PASSTHROUGH
            return self._flush_citations()
        parsed = self._parse_found(self._buffer.strip())
        if parsed is None:
            return self._fail_open()
        if parsed:
            self._mode = _Mode.PASSTHROUGH
            return self._flush_citations()
        self._mode = _Mode.REFUSED
        self._refused = True
        return [QueryEvent.refusal(FIXED_REFUSAL_MESSAGE)]

    def _resolve_first_line(self, newline_index: int) -> list[QueryEvent]:
        """缓冲区里出现了换行符:对第一行做 `{"found": ...}` 判定。"""
        line = self._buffer[:newline_index].strip()
        rest = self._buffer[newline_index + 1 :]
        parsed = self._parse_found(line)
        if parsed is None:
            # 首行不是合法 JSON:fail-open,整段缓冲区当正文透传 + 补发引用。
            return self._fail_open()
        if parsed:
            self._mode = _Mode.PASSTHROUGH
            events = self._flush_citations()
            if rest:
                # 换行后的内容是正文,直接转成 CHUNK 透传,不需要重新走 feed 流程。
                events.append(QueryEvent.chunk(rest))
            return events
        self._mode = _Mode.REFUSED
        self._refused = True
        return [QueryEvent.refusal(FIXED_REFUSAL_MESSAGE)]

    def _fail_open(self) -> list[QueryEvent]:
        """放弃解析,把已缓冲内容当正文透传 + 补发引用。Java 版 `failOpen(content)`。"""
        self._mode = _Mode.PASSTHROUGH
        events = self._flush_citations()
        events.append(QueryEvent.chunk(self._buffer))
        return events

    def _flush_citations(self) -> list[QueryEvent]:
        """把被延迟的引用一次性补发。对应 Java `flushCitations()`。"""
        return [QueryEvent.source(citation) for citation in self._citations]

    @staticmethod
    def _parse_found(line: str) -> bool | None:
        """把候选首行解析成布尔值,失败返回 None。Java `parseFound` 同款语义。"""
        if not line:
            return None
        try:
            root = json.loads(line)
        except (ValueError, TypeError):
            return None
        if not isinstance(root, dict):
            return None
        found = root.get("found")
        if isinstance(found, bool):
            return found
        return None

    @staticmethod
    def _index_of_newline(text: str) -> int:
        """首个换行符下标,无则返回 -1。手写循环避免 str.find 引入的额外抽象,语义与 Java 版一致。"""
        return text.find("\n")
