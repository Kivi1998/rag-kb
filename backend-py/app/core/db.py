"""SQLAlchemy 异步引擎与会话。Schema 由现有 Flyway 迁移(backend/.../db/migration)管理,
Python 侧不新建迁移工具,只做只读/读写访问层迁移,DDL 权威来源不变。"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

engine = create_async_engine(settings.db_url, pool_size=settings.db_pool_size, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
