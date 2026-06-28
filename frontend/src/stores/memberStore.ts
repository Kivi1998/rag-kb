import { defineStore } from 'pinia'
import { ref } from 'vue'
import { memberApi } from '@/api/memberApi'
import type { Member, MemberRole, InviteMemberRequest } from '@/types/member'

export const useMemberStore = defineStore('member', () => {
  // State
  const members = ref<Member[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  // Actions
  async function loadMembers() {
    loading.value = true
    error.value = null
    try {
      members.value = await memberApi.list()
    } catch (e: any) {
      error.value = e?.message || '加载成员列表失败'
    } finally {
      loading.value = false
    }
  }

  async function inviteMember(subjectId: string, role: MemberRole): Promise<boolean> {
    try {
      const req: InviteMemberRequest = { subjectId, role }
      const member = await memberApi.invite(req)
      members.value.push(member)
      return true
    } catch {
      return false
    }
  }

  async function updateRole(id: string, role: MemberRole): Promise<boolean> {
    try {
      const updated = await memberApi.updateRole(id, { role })
      const idx = members.value.findIndex((m) => m.id === id)
      if (idx !== -1) {
        members.value[idx] = updated
      }
      return true
    } catch {
      return false
    }
  }

  async function resetPassword(id: string): Promise<string | null> {
    try {
      const tempPassword = await memberApi.resetPassword(id)
      return tempPassword
    } catch {
      return null
    }
  }

  return { members, loading, error, loadMembers, inviteMember, updateRole, resetPassword }
})
