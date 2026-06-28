/** 团队 DTO（对应后端 Team 实体） */
export interface Team {
  id: string
  name: string
  createdAt: string
  updatedAt: string
}

/** 创建团队请求 */
export interface CreateTeamRequest {
  name: string
}
