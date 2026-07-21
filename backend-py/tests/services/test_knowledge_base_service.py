"""KnowledgeBaseService 业务编排测试。

对照 Java 版 `service/KnowledgeBaseService.java`。
关键不变量:
- 所有 KB 操作必须先经过 `get_by_id_and_current_org` 校验(越权/不存在 → 404)
- 创建时 org/creator 都必须存在,缺一不可
- 列表/查询都按当前 org_id 过滤
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.tenant_context import TenantContext
from app.exceptions.errors import ResourceNotFoundException
from app.models.enums import KbStatus
from app.services.knowledge_base_service import KnowledgeBaseService


@pytest.fixture
def set_tenant():
    from app.core import tenant_context

    def _set(org_id, member_id, role="OWNER"):
        tenant_context._tenant_context.set(
            TenantContext(org_id=org_id, member_id=member_id, role=role)
        )

    return _set


def _build_service():
    kb_repo = AsyncMock()
    org_repo = AsyncMock()
    member_repo = AsyncMock()
    session = AsyncMock()
    service = KnowledgeBaseService(kb_repo, org_repo, member_repo, session)
    return service, kb_repo, org_repo, member_repo, session


class TestCreate:
    @pytest.mark.asyncio
    async def test_create_persists_kb_with_active_status(self, set_tenant):
        org_id, member_id = uuid4(), uuid4()
        set_tenant(org_id, member_id)
        service, kb_repo, org_repo, member_repo, session = _build_service()
        org_repo.find_by_id.return_value = MagicMock(id=org_id)
        member_repo.find_by_id.return_value = MagicMock(id=member_id)

        async def _save(kb):
            if kb.id is None:
                kb.id = uuid4()
            return kb

        kb_repo.save.side_effect = _save

        kb = await service.create("技术文档库")

        assert kb.org_id == org_id
        assert kb.name == "技术文档库"
        assert kb.created_by == member_id
        # 新建时默认 ACTIVE
        assert kb.status == KbStatus.ACTIVE
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_create_org_not_found(self, set_tenant):
        set_tenant(uuid4(), uuid4())
        service, _kb_repo, org_repo, member_repo, _session = _build_service()
        org_repo.find_by_id.return_value = None
        member_repo.find_by_id.return_value = MagicMock()

        with pytest.raises(ResourceNotFoundException):
            await service.create("x")

    @pytest.mark.asyncio
    async def test_create_creator_not_found(self, set_tenant):
        set_tenant(uuid4(), uuid4())
        service, _kb_repo, org_repo, member_repo, _session = _build_service()
        org_repo.find_by_id.return_value = MagicMock()
        member_repo.find_by_id.return_value = None

        with pytest.raises(ResourceNotFoundException):
            await service.create("x")


class TestGetByIdAndCurrentOrg:
    @pytest.mark.asyncio
    async def test_get_returns_kb_when_owned(self, set_tenant):
        org_id, member_id = uuid4(), uuid4()
        set_tenant(org_id, member_id)
        kb_id = uuid4()
        service, kb_repo, _org_repo, _member_repo, _session = _build_service()
        kb_repo.find_by_id_and_org_id.return_value = MagicMock(id=kb_id)

        result = await service.get_by_id_and_current_org(kb_id)
        assert result.id == kb_id
        # 关键:必须按 (id, org_id) 过滤
        kb_repo.find_by_id_and_org_id.assert_awaited_with(kb_id, org_id)

    @pytest.mark.asyncio
    async def test_get_raises_404_when_not_found(self, set_tenant):
        set_tenant(uuid4(), uuid4())
        service, kb_repo, _org_repo, _member_repo, _session = _build_service()
        kb_repo.find_by_id_and_org_id.return_value = None

        with pytest.raises(ResourceNotFoundException):
            await service.get_by_id_and_current_org(uuid4())


class TestList:
    @pytest.mark.asyncio
    async def test_list_scoped_to_current_org(self, set_tenant):
        org_id, member_id = uuid4(), uuid4()
        set_tenant(org_id, member_id)
        service, kb_repo, _org_repo, _member_repo, _session = _build_service()
        kb_repo.find_by_org_id.return_value = [MagicMock(), MagicMock()]

        kbs = await service.list_by_current_org()
        assert len(kbs) == 2
        kb_repo.find_by_org_id.assert_awaited_with(org_id)


class TestUpdate:
    @pytest.mark.asyncio
    async def test_update_renames_kb(self, set_tenant):
        set_tenant(uuid4(), uuid4())
        kb_id = uuid4()
        service, kb_repo, _org_repo, _member_repo, session = _build_service()
        existing = MagicMock()
        existing.id = kb_id
        existing.name = "old"
        kb_repo.find_by_id_and_org_id.return_value = existing
        kb_repo.save.side_effect = lambda k: k

        updated = await service.update(kb_id, "new name")
        assert updated.name == "new name"
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_update_404_when_not_owned(self, set_tenant):
        set_tenant(uuid4(), uuid4())
        service, kb_repo, _org_repo, _member_repo, _session = _build_service()
        kb_repo.find_by_id_and_org_id.return_value = None

        with pytest.raises(ResourceNotFoundException):
            await service.update(uuid4(), "new")


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_returns_true_and_commits(self, set_tenant):
        set_tenant(uuid4(), uuid4())
        kb_id = uuid4()
        service, kb_repo, _org_repo, _member_repo, session = _build_service()
        existing = MagicMock()
        existing.id = kb_id
        kb_repo.find_by_id_and_org_id.return_value = existing

        result = await service.delete(kb_id)
        assert result is True
        kb_repo.delete.assert_awaited_with(existing)
        session.commit.assert_awaited()
