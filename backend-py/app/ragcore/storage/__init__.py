"""对象存储子包。对应 Java 版 `ragcore/storage/`。

公共 API:
    ObjectStorage (Protocol)
    PresignedUpload, StoredObject (值对象)
    LocalObjectStorage, MinioObjectStorage (实现)
"""

from app.ragcore.storage.local_object_storage import LocalObjectStorage
from app.ragcore.storage.minio_object_storage import MinioObjectStorage
from app.ragcore.storage.object_storage import ObjectStorage, PresignedUpload, StoredObject

__all__ = [
    "ObjectStorage",
    "PresignedUpload",
    "StoredObject",
    "LocalObjectStorage",
    "MinioObjectStorage",
]
