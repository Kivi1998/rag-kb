"""对应 repository/OrganizationRepository.java —— Java 版只继承 JpaRepository,没有任何
自定义查询方法,这里同样只提供 BaseRepository 的通用 CRUD。"""

from app.models.organization import Organization
from app.repositories.base import BaseRepository


class OrganizationRepository(BaseRepository[Organization]):
    model = Organization
