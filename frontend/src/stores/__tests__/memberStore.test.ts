import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useMemberStore } from '../memberStore'

vi.mock('@/api/memberApi', () => ({
  memberApi: {
    list: vi.fn(),
    invite: vi.fn(),
    updateRole: vi.fn(),
    resetPassword: vi.fn()
  }
}))

import { memberApi } from '@/api/memberApi'

const mockMember = (overrides = {}) => ({
  id: 'm-1',
  subjectId: 'user-1',
  role: 'MEMBER' as const,
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
  ...overrides
})

describe('memberStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('loadMembers 成功', async () => {
    const members = [mockMember(), mockMember({ id: 'm-2', subjectId: 'user-2', role: 'ADMIN' })]
    vi.mocked(memberApi.list).mockResolvedValue(members)

    const store = useMemberStore()
    await store.loadMembers()

    expect(store.members).toHaveLength(2)
    expect(store.error).toBeNull()
    expect(store.loading).toBe(false)
  })

  it('loadMembers 失败设置 error', async () => {
    vi.mocked(memberApi.list).mockRejectedValue(new Error('网络错误'))

    const store = useMemberStore()
    await store.loadMembers()

    expect(store.members).toHaveLength(0)
    expect(store.error).toBe('网络错误')
    expect(store.loading).toBe(false)
  })

  it('inviteMember 成功添加到列表', async () => {
    const newMember = mockMember({ id: 'm-new', subjectId: 'user-new' })
    vi.mocked(memberApi.invite).mockResolvedValue(newMember)

    const store = useMemberStore()
    const ok = await store.inviteMember('user-new', 'MEMBER')

    expect(ok).toBe(true)
    expect(store.members).toContainEqual(newMember)
  })

  it('inviteMember 失败返回 false', async () => {
    vi.mocked(memberApi.invite).mockRejectedValue(new Error('已存在'))

    const store = useMemberStore()
    const ok = await store.inviteMember('user-1', 'MEMBER')

    expect(ok).toBe(false)
  })

  it('updateRole 成功更新列表中的成员', async () => {
    const updated = mockMember({ role: 'ADMIN' })
    vi.mocked(memberApi.updateRole).mockResolvedValue(updated)

    const store = useMemberStore()
    store.members = [mockMember()]
    const ok = await store.updateRole('m-1', 'ADMIN')

    expect(ok).toBe(true)
    expect(store.members[0].role).toBe('ADMIN')
  })

  it('resetPassword 成功返回临时密码', async () => {
    vi.mocked(memberApi.resetPassword).mockResolvedValue('Temp123!abc')

    const store = useMemberStore()
    const pwd = await store.resetPassword('m-1')

    expect(pwd).toBe('Temp123!abc')
  })

  it('resetPassword 失败返回 null', async () => {
    vi.mocked(memberApi.resetPassword).mockRejectedValue(new Error('失败'))

    const store = useMemberStore()
    const pwd = await store.resetPassword('m-1')

    expect(pwd).toBeNull()
  })
})
