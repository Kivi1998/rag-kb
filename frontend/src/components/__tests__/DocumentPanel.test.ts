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

/** jsdom 里 `input.files` 是只读属性，测试环境下用 defineProperty 注入伪造 FileList 再触发 change。 */
function selectFiles(wrapper: ReturnType<typeof mount>, files: File[]) {
  const input = wrapper.find('input[type="file"]').element as HTMLInputElement
  Object.defineProperty(input, 'files', { value: files, configurable: true })
  input.dispatchEvent(new Event('change'))
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

describe('DocumentPanel 多文件上传', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(documentsApi.list).mockResolvedValue([])
  })

  it('一次选择多个文件时逐个调用上传接口', async () => {
    vi.mocked(documentsApi.upload).mockResolvedValue(failedDocument as never)
    const wrapper = mount(DocumentPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await flushPromises()

    const files = [
      new File(['a'], 'a.md', { type: 'text/markdown' }),
      new File(['b'], 'b.md', { type: 'text/markdown' }),
      new File(['c'], 'c.md', { type: 'text/markdown' })
    ]
    selectFiles(wrapper, files)
    await flushPromises()

    expect(documentsApi.upload).toHaveBeenCalledTimes(3)
    expect(vi.mocked(documentsApi.upload).mock.calls.map((call) => call[1].name)).toEqual(['a.md', 'b.md', 'c.md'])
    expect(wrapper.text()).toContain('本次选择 3 个文件')
  })

  it('批次中某个文件上传失败不影响其余文件，且失败项展示错误信息与重试按钮', async () => {
    vi.mocked(documentsApi.upload).mockImplementation(async (_kbId, file) => {
      if (file.name === 'bad.md') throw new Error('不支持的文件类型: md')
      return failedDocument as never
    })
    const wrapper = mount(DocumentPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await flushPromises()

    selectFiles(wrapper, [
      new File(['ok'], 'ok.md', { type: 'text/markdown' }),
      new File(['bad'], 'bad.md', { type: 'text/markdown' })
    ])
    await flushPromises()

    expect(documentsApi.upload).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('失败：不支持的文件类型: md')
    expect(wrapper.text()).toContain('已上传')

    const retryButton = wrapper.findAll('button').find((button) => button.text().includes('重试'))
    expect(retryButton).toBeTruthy()
    vi.mocked(documentsApi.upload).mockResolvedValueOnce(failedDocument as never)
    await retryButton!.trigger('click')
    await flushPromises()
    expect(documentsApi.upload).toHaveBeenCalledTimes(3)
  })

  it('并发上传数不超过 3，第 4 个文件在有槽位释放前保持 pending', async () => {
    const resolvers: Array<() => void> = []
    vi.mocked(documentsApi.upload).mockImplementation(
      () => new Promise((resolve) => { resolvers.push(() => resolve(failedDocument as never)) })
    )
    const wrapper = mount(DocumentPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await flushPromises()

    selectFiles(wrapper, [1, 2, 3, 4].map((n) => new File([`${n}`], `f${n}.md`, { type: 'text/markdown' })))
    await flushPromises()

    // 前 3 个文件已经发起了上传请求，第 4 个还在等待槽位
    expect(documentsApi.upload).toHaveBeenCalledTimes(3)

    resolvers[0]()
    await flushPromises()
    expect(documentsApi.upload).toHaveBeenCalledTimes(4)
  })

  it('清除已完成不影响仍在进行中的上传项', async () => {
    let resolveUpload: (() => void) | undefined
    vi.mocked(documentsApi.upload)
      .mockResolvedValueOnce(failedDocument as never)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveUpload = () => resolve(failedDocument as never) }))
    const wrapper = mount(DocumentPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await flushPromises()

    selectFiles(wrapper, [
      new File(['a'], 'done.md', { type: 'text/markdown' }),
      new File(['b'], 'pending.md', { type: 'text/markdown' })
    ])
    await flushPromises()

    expect(wrapper.text()).toContain('done.md')
    expect(wrapper.text()).toContain('pending.md')

    const clearButton = wrapper.findAll('button').find((button) => button.text().includes('清除已完成'))
    await clearButton!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('done.md')
    expect(wrapper.text()).toContain('pending.md')
    resolveUpload?.()
    await flushPromises()
  })
})
