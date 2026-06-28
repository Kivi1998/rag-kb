import http from './http'
import type { KbDocument } from '@/types/document'

export const docApi = {
  list(kbId: string): Promise<KbDocument[]> {
    return http.get(`/api/v1/knowledge-bases/${kbId}/documents`)
  },

  get(kbId: string, docId: string): Promise<KbDocument> {
    return http.get(`/api/v1/knowledge-bases/${kbId}/documents/${docId}`)
  },

  upload(kbId: string, file: File): Promise<KbDocument> {
    const formData = new FormData()
    formData.append('file', file)
    return http.post(`/api/v1/knowledge-bases/${kbId}/documents`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },

  remove(kbId: string, docId: string): Promise<void> {
    return http.delete(`/api/v1/knowledge-bases/${kbId}/documents/${docId}`)
  }
}
