"""共享 `rag_chunks_v1` 索引的 Elasticsearch 适配器。

对应 Java 版 `ragcore/index/ElasticsearchChunkIndex.java`。所有写入都包含组织、知识库和
文档标识；删除 API 同时强制三个条件，防止误删相同 document_id 之外的数据。混合检索由
`app.ragcore.retrieval.HybridRetriever` 专门实现，本类的 `search()` 与 Java 版一样禁止
真正实现，避免暴露无租户过滤保护的泛型查询入口。
"""

from __future__ import annotations

import asyncio
import logging
import re
from uuid import UUID

from elasticsearch import AsyncElasticsearch, NotFoundError

from app.core.config import Settings
from app.core.config import settings as default_settings
from app.ragcore.index.exceptions import ElasticsearchIndexException
from app.ragcore.index.search_request import SearchRequest
from app.ragcore.model import Chunk, RetrievedChunk

logger = logging.getLogger(__name__)

_SYMBOL_RE = re.compile(r"\b(?:[A-Za-z_$][\w$]*\.)*[A-Za-z_$][\w$]*\b")
_CONFIG_KEY_RE = re.compile(r"^\s*([A-Za-z][\w.-]{1,})\s*[:=]", re.MULTILINE)
_ERROR_CODE_RE = re.compile(r"\b(?:[A-Z][A-Z0-9_]{2,}|ERR(?:OR)?[-_]?\d+)\b")


class ElasticsearchChunkIndex:
    """`LexicalChunkIndex`(与遗留 `ChunkIndex`)端口的 ES 实现。"""

    def __init__(
        self,
        es_client: AsyncElasticsearch,
        cfg: Settings | None = None,
        index_name: str | None = None,
        vector_dimensions: int | None = None,
    ) -> None:
        self._es = es_client
        cfg = cfg or default_settings
        self._index_name = index_name or cfg.rag_es_index_name
        self._vector_dimensions = vector_dimensions or cfg.rag_es_vector_dimensions
        self._visibility_mapping_ensured = False
        self._ensure_lock = asyncio.Lock()

    # ---- ChunkIndex(遗留端口) ----------------------------------------------

    async def upsert(
        self, chunks: list[Chunk], vectors: list[list[float]], embedding_model_version: str
    ) -> None:
        await self.stage(chunks, vectors, embedding_model_version)
        if not chunks:
            return
        boundaries = {
            (chunk.organization_id, chunk.knowledge_base_id, chunk.document_id) for chunk in chunks
        }
        for org_id, kb_id, document_id in boundaries:
            await self.activate_document(org_id, kb_id, document_id)

    async def search(self, request: SearchRequest) -> list[RetrievedChunk]:
        raise NotImplementedError(
            "混合检索由 HybridRetriever 实现，禁止调用无租户过滤保护的通用 search"
        )

    # ---- LexicalChunkIndex --------------------------------------------------

    async def stage(
        self, chunks: list[Chunk], vectors: list[list[float]], embedding_model_version: str
    ) -> None:
        if not chunks:
            return
        if vectors is None or len(chunks) != len(vectors):
            raise ValueError("chunks 与 vectors 必须一一对应")
        await self.ensure_index()
        operations: list[dict] = []
        for chunk, vector in zip(chunks, vectors):
            self._validate_chunk(chunk, vector)
            operations.append({"index": {"_index": self._index_name, "_id": chunk.id}})
            operations.append(self._to_index_document(chunk, vector, embedding_model_version, False))
        try:
            # `refresh="wait_for"`:紧随其后的 `activate_document()` 用 `update_by_query`
            # 按 document_id 检索刚 stage 的这批 chunk 再改 retrieval_ready——ES 默认
            # ~1s 刷新周期,不强制等刷新的话,小文档/embedding 调用够快时,activate 阶段的
            # 检索会看不到刚写入的 chunk(0 命中、0 报错,静默留在 retrieval_ready=false,
            # 文档却已经推进到 READY)。用 wait_for 而不是 true:等下一次即将发生的刷新
            # 即可,不额外强制多刷一次,批量摄取并发写入时开销更低。
            response = await self._es.bulk(index=self._index_name, operations=operations, refresh="wait_for")
        except Exception as ex:  # noqa: BLE001 - 统一包装为可识别异常
            raise ElasticsearchIndexException("ES Bulk 写入失败") from ex
        if response.get("errors"):
            raise ElasticsearchIndexException(f"ES Bulk 写入出现分项失败: {self._first_bulk_error(response)}")

    async def activate_document(
        self, organization_id: UUID, knowledge_base_id: UUID, document_id: UUID
    ) -> None:
        await self._update_visibility(organization_id, knowledge_base_id, document_id, True)

    async def deactivate_document(
        self, organization_id: UUID, knowledge_base_id: UUID, document_id: UUID
    ) -> None:
        await self._update_visibility(organization_id, knowledge_base_id, document_id, False)

    async def delete_by_document_id(
        self, organization_id: UUID, knowledge_base_id: UUID, document_id: UUID
    ) -> None:
        self._require_ids(organization_id, knowledge_base_id, document_id)
        await self.ensure_index()
        query = {
            "bool": {
                "filter": [
                    {"term": {"org_id": str(organization_id)}},
                    {"term": {"kb_id": str(knowledge_base_id)}},
                    {"term": {"document_id": str(document_id)}},
                ]
            }
        }
        try:
            await self._es.delete_by_query(index=self._index_name, query=query, conflicts="proceed")
        except Exception as ex:  # noqa: BLE001
            raise ElasticsearchIndexException("ES 文档 chunk 删除失败") from ex

    # ---- 内部实现 --------------------------------------------------------

    async def ensure_index(self) -> None:
        """幂等创建索引与 mapping；重复调用不会覆盖既有生产 mapping。"""
        try:
            exists = await self._es.indices.exists(index=self._index_name)
        except Exception as ex:  # noqa: BLE001
            raise ElasticsearchIndexException("检查 ES 索引失败") from ex
        if exists:
            await self._ensure_visibility_mapping()
            return

        try:
            await self._es.indices.create(index=self._index_name, mappings=self._index_mappings())
            self._visibility_mapping_ensured = True
        except Exception as ex:  # noqa: BLE001
            # 多实例并发启动时另一个实例可能已经创建；再次确认即可，与 Java 版处理 400 一致。
            if await self._index_exists():
                return
            raise ElasticsearchIndexException("创建 ES chunk 索引失败") from ex

    async def _index_exists(self) -> bool:
        try:
            return bool(await self._es.indices.exists(index=self._index_name))
        except Exception:  # noqa: BLE001
            return False

    def _index_mappings(self) -> dict:
        def keyword() -> dict:
            return {"type": "keyword"}

        properties = {
            "chunk_id": keyword(),
            "org_id": keyword(),
            "kb_id": keyword(),
            "document_id": keyword(),
            "ordinal": {"type": "integer"},
            "content": {"type": "text", "copy_to": "content_search"},
            "content_search": {"type": "text"},
            "content_vector": {
                "type": "dense_vector",
                "dims": self._vector_dimensions,
                "index": True,
                "similarity": "cosine",
            },
            "retrieval_ready": {"type": "boolean"},
            "heading_path": keyword(),
            "source_path": keyword(),
            "page_no": {"type": "integer"},
            "line_start": {"type": "integer"},
            "line_end": {"type": "integer"},
            "language": keyword(),
            "content_hash": keyword(),
            "model_version": keyword(),
            "parser_version": keyword(),
            "chunk_version": keyword(),
            "symbol_names": keyword(),
            "config_keys": keyword(),
            "error_codes": keyword(),
            "metadata": {"type": "object", "dynamic": True},
        }
        return {"dynamic": "strict", "properties": properties}

    async def _ensure_visibility_mapping(self) -> None:
        if self._visibility_mapping_ensured:
            return
        async with self._ensure_lock:
            if self._visibility_mapping_ensured:
                return
            try:
                await self._es.indices.put_mapping(
                    index=self._index_name, properties={"retrieval_ready": {"type": "boolean"}}
                )
                self._visibility_mapping_ensured = True
            except Exception as ex:  # noqa: BLE001
                raise ElasticsearchIndexException("更新 ES retrieval_ready mapping 失败") from ex

    def _to_index_document(
        self, chunk: Chunk, vector: list[float], model_version: str | None, retrieval_ready: bool
    ) -> dict:
        metadata = dict(chunk.metadata or {})
        return {
            "chunk_id": chunk.id,
            "org_id": str(chunk.organization_id),
            "kb_id": str(chunk.knowledge_base_id),
            "document_id": str(chunk.document_id),
            "ordinal": chunk.ordinal,
            "content": chunk.content,
            "content_search": chunk.content,
            "content_vector": list(vector),
            "retrieval_ready": retrieval_ready,
            "heading_path": list(chunk.heading_path or ()),
            "source_path": chunk.source_path,
            "page_no": chunk.page_no,
            "line_start": chunk.line_start,
            "line_end": chunk.line_end,
            "language": chunk.language,
            "content_hash": chunk.content_hash,
            "model_version": model_version or "unknown",
            "parser_version": metadata.get("parserVersion", "v1"),
            "chunk_version": metadata.get("chunkVersion", "v1"),
            "symbol_names": self._extract(_SYMBOL_RE, chunk.content, 128),
            "config_keys": self._extract(_CONFIG_KEY_RE, chunk.content, 64),
            "error_codes": self._extract(_ERROR_CODE_RE, chunk.content, 64),
            "metadata": metadata,
        }

    async def _update_visibility(
        self, organization_id: UUID, knowledge_base_id: UUID, document_id: UUID, ready: bool
    ) -> None:
        self._require_ids(organization_id, knowledge_base_id, document_id)
        await self.ensure_index()
        query = {
            "bool": {
                "filter": [
                    {"term": {"org_id": str(organization_id)}},
                    {"term": {"kb_id": str(knowledge_base_id)}},
                    {"term": {"document_id": str(document_id)}},
                ]
            }
        }
        script = {"source": "ctx._source.retrieval_ready = params.ready", "lang": "painless", "params": {"ready": ready}}
        try:
            await self._es.update_by_query(
                index=self._index_name, query=query, script=script, conflicts="proceed", refresh=True
            )
        except Exception as ex:  # noqa: BLE001
            action = "激活 ES Chunk 失败" if ready else "隐藏 ES Chunk 失败"
            raise ElasticsearchIndexException(action) from ex

    @staticmethod
    def _extract(pattern: re.Pattern[str], content: str, limit: int) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for match in pattern.finditer(content or ""):
            value = match.group(1) if match.groups() and match.group(1) is not None else match.group(0)
            if value not in seen:
                seen.add(value)
                values.append(value)
            if len(values) >= limit:
                break
        return values

    def _validate_chunk(self, chunk: Chunk, vector: list[float]) -> None:
        if chunk is None or not chunk.id or not chunk.content or not chunk.content.strip():
            raise ValueError("chunk id 与 content 不能为空")
        self._require_ids(chunk.organization_id, chunk.knowledge_base_id, chunk.document_id)
        if vector is None or len(vector) != self._vector_dimensions:
            raise ValueError(f"Embedding 向量维度必须为 {self._vector_dimensions}")

    @staticmethod
    def _require_ids(organization_id: UUID | None, knowledge_base_id: UUID | None, document_id: UUID | None) -> None:
        if organization_id is None or knowledge_base_id is None or document_id is None:
            raise ValueError("orgId、kbId 与 documentId 均不能为空")

    @staticmethod
    def _first_bulk_error(response: dict) -> str:
        for item in response.get("items", []):
            operation = item.get("index", {})
            error = operation.get("error")
            if error:
                return error.get("reason", str(operation.get("status", "unknown")))
        return "unknown"
