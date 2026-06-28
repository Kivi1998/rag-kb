import http from './http'
import type { KnowledgeBase } from '@/types/kb'

export const kbApi = {
  list(): Promise<KnowledgeBase[]> {
    return http.get('/api/v1/knowledge-bases')
  },

  create(name: string): Promise<KnowledgeBase> {
    return http.post('/api/v1/knowledge-bases', { name })
  },

  update(id: string, name: string): Promise<KnowledgeBase> {
    return http.put(`/api/v1/knowledge-bases/${id}`, { name })
  },

  remove(id: string): Promise<{ code: number; message?: string }> {
    return http.delete(`/api/v1/knowledge-bases/${id}`)
  }
}
