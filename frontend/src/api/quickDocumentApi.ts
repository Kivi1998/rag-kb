/**
 * 会话内临时文档（长上下文直接塞入模式）：不写入知识库、不切块不索引，只在当前会话有效。
 * 上传接口同步阻塞（后端解析完成才返回），前端调用方需要自行展示等待状态。
 *
 * 本文件不显式标注 axios 泛型，`http.ts` 的响应拦截器已经解包 ApiResponse envelope，
 * 与 documentsApi.ts 保持一致的 `as` 收紧写法。
 */

import http from './http'

export interface QuickDocumentSummary {
  docId: string
  filename: string
  characterCount: number
}

/** 上传是同步阻塞接口，扫描版 PDF/音视频会走后端 OCR/ASR 网关，耗时可能远超 http.ts 默认的
 * 15s 超时。后端网关超时（`rag.parser.multimodal.timeout-ms`）默认 600000ms（10 分钟），
 * 前端这里对齐同一个数值，避免客户端先于服务端放弃、误报"上传失败"。 */
const UPLOAD_TIMEOUT_MS = 600_000

function unwrap<T>(raw: unknown): T {
  return raw as T
}

function basePath(kbId: string, sessionId: string): string {
  return `/api/v1/knowledge-bases/${encodeURIComponent(kbId)}/sessions/${encodeURIComponent(sessionId)}/quick-documents`
}

export const quickDocumentApi = {
  async upload(kbId: string, sessionId: string, file: File): Promise<QuickDocumentSummary> {
    const form = new FormData()
    form.append('file', file)
    const res = await http.post(basePath(kbId, sessionId), form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: UPLOAD_TIMEOUT_MS
    })
    return unwrap<QuickDocumentSummary>(res)
  },

  async list(kbId: string, sessionId: string): Promise<QuickDocumentSummary[]> {
    const res = await http.get(basePath(kbId, sessionId))
    return unwrap<QuickDocumentSummary[]>(res)
  },

  async remove(kbId: string, sessionId: string, docId: string): Promise<void> {
    await http.delete(`${basePath(kbId, sessionId)}/${encodeURIComponent(docId)}`)
  }
}
