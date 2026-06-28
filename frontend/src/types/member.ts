/** 成员角色（与后端 MemberRole 枚举一致） */
export type MemberRole = 'OWNER' | 'ADMIN' | 'MEMBER'

/** 成员 DTO（对应后端 Member 实体） */
export interface Member {
  id: string
  subjectId: string
  role: MemberRole
  createdAt: string
  updatedAt: string
}

/** 邀请成员请求（将已有用户加入当前组织） */
export interface InviteMemberRequest {
  subjectId: string
  role: MemberRole
}

/** 修改角色请求 */
export interface UpdateRoleRequest {
  role: MemberRole
}
