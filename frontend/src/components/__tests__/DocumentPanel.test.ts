import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('element-plus', async () => {
  const actual = await vi.importActual<typeof import('element-plus')>('element-plus')
  return { ...actual, ElMessage: { success: vi.fn(), error: vi.fn() }, ElMessageBox: { confirm: vi.fn() } }
})
vi.mock('@/api/documentsApi', () => ({
  documentsApi: { list: vi.fn(), upload: vi.fn(), retry: vi.fn(), remove: vi.fn() }
}))

import DocumentPanel from '@/components/DocumentPanel.vue'
import { documentsApi } from '@/api/documentsApi'
import { ElMessage, ElMessageBox } from 'element-plus'

const failedDocument = {
  documentId: 'doc-1', kbId: 'kb-1', jobId: 'job-1', name: '部署说明.md', size: 1024,
  contentType: 'text/markdown', status: 'FAILED' as const, errorMessage: '解析失败', retryable: true,
  uploadedAt: '2026-07-12T00:00:00Z'
}

describe('DocumentPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(documentsApi.list).mockResolvedValue([failedDocument])
  })

  it('失败文档使用服务端 jobId 重试，而非从前端推导任务标识', async () => {
    const wrapper = mount(DocumentPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await flushPromises()
    const retry = wrapper.findAll('button').find((button) => button.text().includes('重试'))
    expect(retry).toBeTruthy()
    await retry!.trigger('click')
    await flushPromises()
    expect(documentsApi.retry).toHaveBeenCalledWith('kb-1', 'job-1')
    expect(ElMessage.success).toHaveBeenCalledWith('已重新加入摄取队列')
  })

  it('删除操作确认后传递 documentId 与 kbId', async () => {
    vi.mocked(ElMessageBox.confirm).mockResolvedValueOnce('confirm' as never)
    const wrapper = mount(DocumentPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await flushPromises()
    const remove = wrapper.findAll('button').find((button) => button.text().includes('删除'))
    await remove!.trigger('click')
    await flushPromises()
    expect(documentsApi.remove).toHaveBeenCalledWith('kb-1', 'doc-1')
  })
})
