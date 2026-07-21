"""通用 repository 基类,对应 Spring Data JpaRepository<T, ID> 提供的默认 CRUD。

注意:`find_by_id` / `delete` 等按主键操作的方法和 Java 版 `JpaRepository.findById(id)` 一样,
**不做租户过滤** —— 这是 JPA/Spring Data 基类的默认语义,不是本次迁移引入的疏漏。调用方如果
是面向租户的业务路径,必须自行先经过一次带 org_id/kb_id 过滤的查询(如
`find_by_id_and_org_id`)确认归属后,再决定要不要继续用主键做后续操作。
"""

from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_by_id(self, id_: UUID) -> ModelT | None:
        return await self.session.get(self.model, id_)

    async def find_all(self) -> list[ModelT]:
        result = await self.session.execute(select(self.model))
        return list(result.scalars().all())

    async def save(self, entity: ModelT) -> ModelT:
        """对应 JpaRepository.save():新增或更新一个已 attach/待 attach 的实体。"""
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def delete(self, entity: ModelT) -> None:
        await self.session.delete(entity)

    async def delete_by_id(self, id_: UUID) -> None:
        entity = await self.find_by_id(id_)
        if entity is not None:
            await self.session.delete(entity)
