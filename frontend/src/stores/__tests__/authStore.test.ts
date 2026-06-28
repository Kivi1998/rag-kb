import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAuthStore } from '../authStore'

// Mock authApi
vi.mock('@/api/authApi', () => ({
  authApi: {
    login: vi.fn()
  }
}))

// Mock memberApi
vi.mock('@/api/memberApi', () => ({
  memberApi: {
    me: vi.fn()
  }
}))

// Mock router
vi.mock('@/router', () => ({
  default: { push: vi.fn() }
}))

// Mock ElMessage
vi.mock('element-plus', () => ({
  ElMessage: {
    error: vi.fn(),
    success: vi.fn()
  }
}))

import { authApi } from '@/api/authApi'
import { memberApi } from '@/api/memberApi'

describe('authStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    if (typeof sessionStorage !== 'undefined') {
      sessionStorage.clear()
    }
    vi.clearAllMocks()
  })

  it('login 成功存 token + orgId + role', async () => {
    vi.mocked(authApi.login).mockResolvedValue({
      token: 'test-token',
      userId: 'user-1',
      orgId: 'org-1'
    })
    vi.mocked(memberApi.me).mockResolvedValue({
      id: 'member-1',
      subjectId: 'user-1',
      role: 'ADMIN',
      createdAt: '',
      updatedAt: ''
    })

    const store = useAuthStore()
    const result = await store.login('test@test.com', 'Pass1234!')

    expect(result).toBe('ok')
    expect(store.token).toBe('test-token')
    expect(store.orgId).toBe('org-1')
    expect(store.role).toBe('ADMIN')
    expect(sessionStorage.getItem('token')).toBe('test-token')
    expect(sessionStorage.getItem('orgId')).toBe('org-1')
    expect(sessionStorage.getItem('role')).toBe('ADMIN')
  })

  it('login 失败返回 fail', async () => {
    vi.mocked(authApi.login).mockRejectedValue(new Error('登录失败'))

    const store = useAuthStore()
    const result = await store.login('test@test.com', 'wrong')

    expect(result).toBe('fail')
    expect(store.token).toBeNull()
    expect(sessionStorage.getItem('token')).toBeNull()
  })

  it('login 返回 orgId=null 时显示错误提示且不存 token', async () => {
    vi.mocked(authApi.login).mockResolvedValue({
      token: 'test-token',
      userId: 'user-1',
      orgId: null
    })

    const store = useAuthStore()
    const result = await store.login('noorg@test.com', 'Pass1234!')

    expect(result).toBe('fail')
    expect(store.token).toBeNull()
    expect(sessionStorage.getItem('token')).toBeNull()
  })

  it('login mustChangePassword 返回 must_change_password', async () => {
    vi.mocked(authApi.login).mockResolvedValue({
      token: 'test-token',
      userId: 'user-1',
      orgId: 'org-1',
      mustChangePassword: true
    })
    vi.mocked(memberApi.me).mockResolvedValue({
      id: 'member-1',
      subjectId: 'user-1',
      role: 'MEMBER',
      createdAt: '',
      updatedAt: ''
    })

    const store = useAuthStore()
    const result = await store.login('test@test.com', 'Temp1234!')

    expect(result).toBe('must_change_password')
    expect(store.token).toBe('test-token')
  })

  it('logout 清除 sessionStorage', () => {
    sessionStorage.setItem('token', 'test')
    sessionStorage.setItem('username', 'user')
    sessionStorage.setItem('orgId', 'org')
    sessionStorage.setItem('role', 'ADMIN')

    const store = useAuthStore()
    store.logout()

    expect(store.token).toBeNull()
    expect(store.username).toBeNull()
    expect(store.orgId).toBeNull()
    expect(store.role).toBeNull()
    expect(sessionStorage.getItem('token')).toBeNull()
    expect(sessionStorage.getItem('role')).toBeNull()
  })
})
