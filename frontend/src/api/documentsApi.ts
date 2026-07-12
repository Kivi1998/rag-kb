/**
 * 文档工作区 API 占位 Mock 契约（T204 / T101 范围）。
 *
 * 路径：/api/v1/documents
 * 上传只保存原文件 + 创建 `ingestion_job` 并返回 QUEUED；解析在 Worker 异步执行
 * （CLAUDE.md + 任务清单 T101 / T102）。
 *
 * 摄取状态机：QUEUED → PARSING → CHUNKING → EMBEDDING → INDEXING → READY
 * 任何阶段失败 → FAILED；管理员可手动重试。
 *
 * 后端已提供该契约；真实环境仍需以 MinIO、ES、Embedding Worker 完成端到端验收。
 *
 * 本文件不显式标注 axios 泛型，因为 `http.ts` 的响应拦截器已经在内部
 * 解包 ApiResponse envelope（code=0 → data），TS 无法感知到这一变换；
 * 现有 kbApi / authApi 同样不写泛型，靠 `as` 收紧类型。保持一致避免引入
 * 偏离项目惯例的类型黑魔法。
 */

import http from './http'
import type { Document, IngestionJob } from '@/types/ingestion'

export interface ListDocumentsParams {
  /** 必填；服务端按 JWT 解析后再校验归属，禁止前端构造 */
  kbId: string
  /** 状态过滤（可选） */
  status?: Document['status']
}

/** 拦截器已解包，但 axios 类型不会自动收紧：用 `as` 把任意收敛到 DTO */
function unwrap<T>(raw: unknown): T {
  return raw as T
}

export const documentsApi = {
  /** 列出 KB 下的所有文档 */
  async list(params: ListDocumentsParams): Promise<Document[]> {
    const res = await http.get('/api/v1/documents', {
      params: { kbId: params.kbId, status: params.status }
    })
    return unwrap<Document[]>(res)
  },

  /**
   * 上传文件到 KB。上传只是「保存原文件 + 触发摄取任务」，
   * 真正解析由 T102 Worker 异步完成，前端不得在此等待大文件解析。
   * 文件大小白名单：Markdown / TXT / 代码 / YAML/JSON/XML / DOCX / 文本型 PDF
   */
  async upload(kbId: string, file: File, onProgress?: (percent: number) => void): Promise<Document> {
    const form = new FormData()
    form.append('file', file)
    form.append('kbId', kbId)
    const res = await http.post('/api/v1/documents/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: onProgress
        ? (evt) => {
            if (!evt.total) return
            onProgress(Math.round((evt.loaded * 100) / evt.total))
          }
        : undefined
    })
    return unwrap<Document>(res)
  },

  /** 查询摄取状态（用于 KB 详情页轮询展示当前进度） */
  async getJob(kbId: string, jobId: string): Promise<IngestionJob> {
    const res = await http.get(`/api/v1/documents/jobs/${encodeURIComponent(jobId)}`, {
      params: { kbId }
    })
    return unwrap<IngestionJob>(res)
  },

  /**
   * 管理员手动重试失败的摄取任务（T102 验收要求）。
   * 普通用户调用由后端按 RBAC 拒绝；前端无需在 UI 里隐藏按钮，依赖后端兜底。
   */
  async retry(kbId: string, jobId: string): Promise<IngestionJob> {
    const res = await http.post(
      `/api/v1/documents/jobs/${encodeURIComponent(jobId)}/retry`,
      {},
      { params: { kbId } }
    )
    return unwrap<IngestionJob>(res)
  },

  /** 删除文档（同时删除对象存储 + ES chunk，依赖 T102 的删除补偿） */
  async remove(kbId: string, documentId: string): Promise<void> {
    await http.delete(`/api/v1/documents/${encodeURIComponent(documentId)}`, {
      params: { kbId }
    })
  }
}
