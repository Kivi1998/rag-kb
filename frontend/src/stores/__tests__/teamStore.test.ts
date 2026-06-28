import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useTeamStore } from '../teamStore'

vi.mock('@/api/teamApi', () => ({
  teamApi: {
    list: vi.fn(),
    create: vi.fn()
  }
}))

import { teamApi } from '@/api/teamApi'

describe('teamStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('loadTeams 成功', async () => {
    const teams = [
      { id: 't-1', name: '工程团队', createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z' }
    ]
    vi.mocked(teamApi.list).mockResolvedValue(teams)

    const store = useTeamStore()
    await store.loadTeams()

    expect(store.teams).toHaveLength(1)
    expect(store.error).toBeNull()
  })

  it('loadTeams 失败设置 error', async () => {
    vi.mocked(teamApi.list).mockRejectedValue(new Error('加载失败'))

    const store = useTeamStore()
    await store.loadTeams()

    expect(store.teams).toHaveLength(0)
    expect(store.error).toBe('加载失败')
  })

  it('createTeam 成功添加到列表', async () => {
    const team = { id: 't-new', name: '新团队', createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:00:00Z' }
    vi.mocked(teamApi.create).mockResolvedValue(team)

    const store = useTeamStore()
    const ok = await store.createTeam('新团队')

    expect(ok).toBe(true)
    expect(store.teams).toContainEqual(team)
  })

  it('createTeam 失败返回 false', async () => {
    vi.mocked(teamApi.create).mockRejectedValue(new Error('创建失败'))

    const store = useTeamStore()
    const ok = await store.createTeam('新团队')

    expect(ok).toBe(false)
  })
})
