import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/queryApi', () => ({
  openStream: vi.fn(),
  queryStreamUrl: vi.fn(() => '/api/v1/knowledge-bases/kb-1/query')
}))

import ChatPanel from '@/components/ChatPanel.vue'
import { openStream } from '@/api/queryApi'
import { useAuthStore } from '@/stores/authStore'

function streamOf<T>(events: T[]): AsyncGenerator<T> {
  return (async function* () { for (const event of events) yield event })()
}

describe('ChatPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    const auth = useAuthStore()
    auth.token = 'token-1'
    auth.orgId = 'org-1'
    if (!crypto.randomUUID) Object.defineProperty(crypto, 'randomUUID', { value: () => 'test-id' })
  })

  it('累积 SSE 文本、来源和拒答，并始终使用当前 kb 路径与认证头', async () => {
    vi.mocked(openStream).mockReturnValue(streamOf([
      { eventType: 'source', data: { citation: { documentId: 'd1', documentName: '部署说明.md', headingPath: ['部署'], snippet: '检查数据库连接', pageNo: 2, lineStart: 4, lineEnd: 5, score: 0.91 } } },
      { eventType: 'chunk', data: { content: '请检查数据库连接。' } },
      { eventType: 'done', data: {} }
    ]) as never)
    const wrapper = mount(ChatPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await wrapper.find('textarea').setValue('如何排查启动失败？')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(openStream).toHaveBeenCalledWith(expect.objectContaining({
      url: '/api/v1/knowledge-bases/kb-1/query',
      body: { question: '如何排查启动失败？' },
      headers: { Authorization: 'Bearer token-1', 'X-Org-Id': 'org-1' }
    }))
    expect(wrapper.text()).toContain('请检查数据库连接。')
    expect(wrapper.text()).toContain('部署说明.md')
    expect(wrapper.text()).toContain('第 2 页')
  })

  it('refusal 显示为正常检索不足状态，而不是模型回答', async () => {
    vi.mocked(openStream).mockReturnValue(streamOf([
      { eventType: 'refusal', data: { message: '未在当前知识库中检索到足够依据' } }
    ]) as never)
    const wrapper = mount(ChatPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await wrapper.find('textarea').setValue('不存在的问题')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('检索结果')
    expect(wrapper.text()).toContain('未在当前知识库中检索到足够依据')
  })

  it('回车直接发送', async () => {
    vi.mocked(openStream).mockReturnValue(streamOf([{ eventType: 'done', data: {} }]) as never)
    const wrapper = mount(ChatPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await wrapper.find('textarea').setValue('回车发送测试')
    await wrapper.find('textarea').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(openStream).toHaveBeenCalledWith(expect.objectContaining({ body: { question: '回车发送测试' } }))
  })

  it('shift+回车换行，不发送', async () => {
    const wrapper = mount(ChatPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await wrapper.find('textarea').setValue('第一行')
    await wrapper.find('textarea').trigger('keydown', { key: 'Enter', shiftKey: true })
    await flushPromises()
    expect(openStream).not.toHaveBeenCalled()
  })

  it('中文输入法候选词确认（isComposing）时的回车不触发发送', async () => {
    const wrapper = mount(ChatPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await wrapper.find('textarea').setValue('拼音候选中')
    await wrapper.find('textarea').trigger('keydown', { key: 'Enter', isComposing: true })
    await flushPromises()
    expect(openStream).not.toHaveBeenCalled()
  })
})
