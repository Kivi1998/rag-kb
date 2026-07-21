"""索引层可识别异常。对应 Java 版 `ragcore/index/ElasticsearchIndexException.java`、
`ragcore/index/MilvusVectorException.java`。
"""

from __future__ import annotations


class ElasticsearchIndexException(RuntimeError):
    """Elasticsearch 索引/查询失败时抛出的可识别异常。"""


class MilvusVectorException(RuntimeError):
    """Milvus Collection 管理或向量索引操作失败时抛出的可识别异常。"""
