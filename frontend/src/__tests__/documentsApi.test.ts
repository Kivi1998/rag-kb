import { describe, expect, it, vi, beforeEach } from 'vitest'
import { documentsApi } from '@/api/documentsApi'

/**
 * documentsApi 测试 —— T005 / T206 范围。
 *
 * 注意：
 * - 上传只触发 ingestion_job（QUEUED），不解析；前端不在此等待大文件解析
 * - kbId 由路径/查询串带出给后端做服务端租户过滤；前端不得构造 orgId/kbId 头
 * - 任何带 kbId 的请求最终都依赖后端按 X-Org-Id 做 RBAC 校验（CLAUDE.md 红线）
 */

vi.mock('@/api/http', () => {
  return {
    default: {
      get: vi.fn(),
      post: vi.fn(),
      delete: vi.fn()
    }
  }
})

import http from '@/api/http'
const httpGet = http.get as unknown as ReturnType<typeof vi.fn>
const httpPost = http.post as unknown as ReturnType<typeof vi.fn>
const httpDelete = http.delete as unknown as ReturnType<typeof vi.fn>

const orgId = 'org-99'
const kbId = 'kb-1'

describe('documentsApi', () => {
  beforeEach(() => {
    httpGet.mockReset()
    httpPost.mockReset()
    httpDelete.mockReset()
  })

  it('list 把 status 通过 query 串传给后端', async () => {
    httpGet.mockResolvedValueOnce([])
    await documentsApi.list({ kbId, status: 'READY' })
    expect(httpGet).toHaveBeenCalledWith('/api/v1/documents', {
      params: { kbId, status: 'READY' }
    })
  })

  it('upload 必须把 kbId 放进 multipart 字段里', async () => {
    const createdDoc = {
      documentId: 'd1',
      kbId,
      name: 'a.md',
      size: 12,
      contentType: 'text/markdown',
      status: 'QUEUED' as const,
      uploadedAt: '2026-07-10T00:00:00Z'
    }
    httpPost.mockResolvedValueOnce(createdDoc)

    const file = new File(['hello'], 'a.md', { type: 'text/markdown' })
    const doc = await documentsApi.upload(kbId, file)

    expect(doc.status).toBe('QUEUED')
    expect(httpPost).toHaveBeenCalledTimes(1)
    const [path, form] = (httpPost.mock.calls[0] as unknown as [string, FormData, object])
    expect(path).toBe('/api/v1/documents/upload')
    expect(form).toBeInstanceOf(FormData)
    // 关键：kbId 必须放进表单（白名单由后端校验文件类型）
    expect((form as unknown as FormData).get('kbId')).toBe(kbId)
    expect((form as unknown as FormData).get('file')).toBe(file)
  })

  it('retry 必须明确传 kbId 给后端做归属过滤', async () => {
    httpPost.mockResolvedValueOnce({ jobId: 'j1', documentId: 'd1', kbId, status: 'QUEUED' })
    await documentsApi.retry(kbId, 'j1')
    expect(httpPost).toHaveBeenCalledWith(
      '/api/v1/documents/jobs/j1/retry',
      {},
      { params: { kbId } }
    )
  })

  it('remove 删除必须携带 kbId（防止跨 KB 删除）', async () => {
    httpDelete.mockResolvedValueOnce(undefined)
    await documentsApi.remove(kbId, 'd1')
    expect(httpDelete).toHaveBeenCalledWith('/api/v1/documents/d1', { params: { kbId } })
  })

  it('getJob 通过 URL 段传 jobId，通过 query 传 kbId', async () => {
    httpGet.mockResolvedValueOnce({ jobId: 'j1' })
    await documentsApi.getJob(kbId, 'j1')
    expect(httpGet).toHaveBeenCalledWith('/api/v1/documents/jobs/j1', {
      params: { kbId }
    })
  })
})
