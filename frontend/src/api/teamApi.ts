import http from './http'
import type { Team } from '@/types/team'

export const teamApi = {
  /** 获取当前组织团队列表 */
  list(): Promise<Team[]> {
    return http.get('/api/v1/teams')
  },

  /** 创建团队 */
  create(name: string): Promise<Team> {
    return http.post('/api/v1/teams', { name })
  }
}
