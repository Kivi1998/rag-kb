import { defineStore } from 'pinia'
import { ref } from 'vue'
import { teamApi } from '@/api/teamApi'
import type { Team } from '@/types/team'

export const useTeamStore = defineStore('team', () => {
  // State
  const teams = ref<Team[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  // Actions
  async function loadTeams() {
    loading.value = true
    error.value = null
    try {
      teams.value = await teamApi.list()
    } catch (e: any) {
      error.value = e?.message || '加载团队列表失败'
    } finally {
      loading.value = false
    }
  }

  async function createTeam(name: string): Promise<boolean> {
    try {
      const team = await teamApi.create(name)
      teams.value.push(team)
      return true
    } catch {
      return false
    }
  }

  return { teams, loading, error, loadTeams, createTeam }
})
