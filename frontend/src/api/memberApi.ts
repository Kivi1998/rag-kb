import http from './http'
import type { Member, InviteMemberRequest, UpdateRoleRequest } from '@/types/member'

export const memberApi = {
  /** 获取当前组织成员列表 */
  list(): Promise<Member[]> {
    return http.get('/api/v1/members')
  },

  /** 获取当前登录用户的成员信息（含 role） */
  me(): Promise<Member> {
    return http.get('/api/v1/members/me')
  },

  /** 邀请（添加已有用户到当前组织） */
  invite(req: InviteMemberRequest): Promise<Member> {
    return http.post('/api/v1/members', req)
  },

  /** 修改成员角色 */
  updateRole(id: string, req: UpdateRoleRequest): Promise<Member> {
    return http.patch(`/api/v1/members/${id}/role`, req)
  },

  /** 重置密码（返回后端生成的临时密码） */
  resetPassword(id: string): Promise<string> {
    return http.post(`/api/v1/members/${id}/reset-password`)
  }
}
