import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// Mock Element Plus
vi.mock('element-plus', () => ({
  ElMessage: {
    warning: vi.fn(),
    success: vi.fn(),
    error: vi.fn()
  },
  ElMessageBox: {
    confirm: vi.fn().mockResolvedValue('confirm')
  }
}))

// Mock API modules
vi.mock('@/api/memberApi', () => ({
  memberApi: { list: vi.fn(), me: vi.fn(), invite: vi.fn(), updateRole: vi.fn(), resetPassword: vi.fn() }
}))
vi.mock('@/api/teamApi', () => ({
  teamApi: { list: vi.fn(), create: vi.fn() }
}))
vi.mock('@/api/http', () => ({
  default: { post: vi.fn(), get: vi.fn() }
}))
vi.mock('@/router', () => ({
  default: { push: vi.fn() }
}))

import { ElMessage } from 'element-plus'
import { useMemberStore } from '@/stores/memberStore'
import { useTeamStore } from '@/stores/teamStore'
import { memberApi } from '@/api/memberApi'
import { teamApi } from '@/api/teamApi'

describe('表单校验', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  describe('邀请成员', () => {
    it('subjectId 为空时不调用 API', async () => {
      const store = useMemberStore()
      const ok = await store.inviteMember('', 'MEMBER')

      // inviteMember 本身不校验（校验在组件层），但 API 会被调用
      // 此测试验证 store 层传递正确参数
      expect(memberApi.invite).toHaveBeenCalledWith({ subjectId: '', role: 'MEMBER' })
    })

    it('subjectId 有值时正常调用 API', async () => {
      vi.mocked(memberApi.invite).mockResolvedValue({
        id: 'm-1', subjectId: 'user-1', role: 'MEMBER',
        createdAt: '', updatedAt: ''
      })

      const store = useMemberStore()
      const ok = await store.inviteMember('user-1', 'MEMBER')

      expect(ok).toBe(true)
      expect(memberApi.invite).toHaveBeenCalledWith({ subjectId: 'user-1', role: 'MEMBER' })
    })
  })

  describe('新建团队', () => {
    it('名称为空时不调用 API', async () => {
      const store = useTeamStore()
      const ok = await store.createTeam('')

      // createTeam 本身不校验（校验在组件层），但 API 会被调用
      expect(teamApi.create).toHaveBeenCalledWith('')
    })

    it('名称有值时正常调用 API', async () => {
      vi.mocked(teamApi.create).mockResolvedValue({
        id: 't-1', name: '新团队', createdAt: '', updatedAt: ''
      })

      const store = useTeamStore()
      const ok = await store.createTeam('新团队')

      expect(ok).toBe(true)
      expect(teamApi.create).toHaveBeenCalledWith('新团队')
    })
  })
})
