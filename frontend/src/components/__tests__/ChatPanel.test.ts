import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/queryApi', () => ({
  openStream: vi.fn(),
  queryStreamUrl: vi.fn(() => '/api/v1/knowledge-bases/kb-1/query'),
  createSession: vi.fn(() => Promise.resolve('session-1')),
  getSessionMessages: vi.fn(() => Promise.reject(new Error('HTTP 404'))),
  listSessions: vi.fn(() => Promise.resolve([])),
  deleteSession: vi.fn(() => Promise.resolve())
}))

import ChatPanel from '@/components/ChatPanel.vue'
import { createSession, getSessionMessages, openStream } from '@/api/queryApi'
import { useAuthStore } from '@/stores/authStore'

function streamOf<T>(events: T[]): AsyncGenerator<T> {
  return (async function* () { for (const event of events) yield event })()
}

/** 打字机节流展示用真实 setInterval，测试里切到 fake timer 并推进足够时长把
 * 缓冲区吐完，否则 flushPromises() 之后内容还停留在缓冲区里没显现出来。 */
async function drainReveal() {
  await vi.advanceTimersByTimeAsync(2000)
}

describe('ChatPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(createSession).mockResolvedValue('session-1')
    vi.mocked(getSessionMessages).mockRejectedValue(new Error('HTTP 404'))
    vi.useFakeTimers()
    const auth = useAuthStore()
    auth.token = 'token-1'
    auth.orgId = 'org-1'
    if (!crypto.randomUUID) Object.defineProperty(crypto, 'randomUUID', { value: () => 'test-id' })
    localStorage.clear() // 每个用例默认无历史会话记录，走"新建会话"路径；需要恢复行为的用例自行预置
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('累积 SSE 文本、来源和拒答，并始终使用当前 kb 路径与认证头', async () => {
    vi.mocked(openStream).mockReturnValue(streamOf([
      { eventType: 'source', data: { citation: { documentId: 'd1', documentName: '部署说明.md', headingPath: ['部署'], snippet: '检查数据库连接', pageNo: 2, lineStart: 4, lineEnd: 5, score: 0.91 } } },
      { eventType: 'chunk', data: { content: '请检查数据库连接。' } },
      { eventType: 'done', data: {} }
    ]) as never)
    const wrapper = mount(ChatPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await flushPromises() // 等待挂载时自动创建的会话(createSession)完成，否则 sessionId 未就绪、canSend 恒为 false
    await wrapper.find('textarea').setValue('如何排查启动失败？')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    await drainReveal()

    expect(openStream).toHaveBeenCalledWith(expect.objectContaining({
      url: '/api/v1/knowledge-bases/kb-1/query',
      body: { question: '如何排查启动失败？', sessionId: 'session-1' },
      headers: { Authorization: 'Bearer token-1', 'X-Org-Id': 'org-1' }
    }))
    expect(wrapper.text()).toContain('请检查数据库连接。')
    // 引用来源不再默认展示在回答下方（改为点击 [资料N] 才在右侧抽屉展示），
    // 所以这里不断言"部署说明.md"/"第 2 页"这些原来的卡片内容。
  })

  it('引用来源默认不展示在回答下方；点击正文里的 [资料N] 才在右侧抽屉展示对应那一条', async () => {
    vi.mocked(openStream).mockReturnValue(streamOf([
      { eventType: 'source', data: { citation: { documentId: 'd1', documentName: '部署说明.md', headingPath: ['部署'], snippet: '检查数据库连接的详细说明', pageNo: 2, lineStart: 4, lineEnd: 5, score: 0.91 } } },
      { eventType: 'chunk', data: { content: '请检查数据库连接 [资料1]。' } },
      { eventType: 'done', data: {} }
    ]) as never)
    const wrapper = mount(ChatPanel, {
      props: { kbId: 'kb-1' },
      global: { plugins: [ElementPlus] },
      attachTo: document.body
    })
    await flushPromises()
    await wrapper.find('textarea').setValue('如何排查启动失败？')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    await drainReveal()

    // 默认不展示来源卡片/片段内容。
    expect(wrapper.text()).not.toContain('部署说明.md')
    expect(document.body.textContent).not.toContain('检查数据库连接的详细说明')

    const ref = wrapper.find('.citation-ref')
    expect(ref.exists()).toBe(true)
    expect(ref.attributes('data-ref')).toBe('1')
    await ref.trigger('click')
    await flushPromises()

    // el-drawer 默认 teleport 到 document.body，不在 wrapper 的 DOM 子树内，需要直接查 body。
    const drawer = document.querySelector('[data-testid="citation-drawer"]')
    expect(drawer).not.toBeNull()
    expect(drawer?.textContent).toContain('部署说明.md')
    expect(drawer?.textContent).toContain('检查数据库连接的详细说明')
    expect(drawer?.textContent).toContain('第 2 页')

    wrapper.unmount()
  })

  it('self_check_warning 事件渲染为警示提醒块，不影响正文与来源展示', async () => {
    vi.mocked(openStream).mockReturnValue(streamOf([
      { eventType: 'chunk', data: { content: '这是一句正文内容。' } },
      { eventType: 'self_check_warning', data: { message: '⚠️ 自检提示：以下内容未在参考资料中找到明确支撑：\n- 示例断言' } },
      { eventType: 'done', data: {} }
    ]) as never)
    const wrapper = mount(ChatPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await flushPromises()
    await wrapper.find('textarea').setValue('这句话有没有依据？')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    await drainReveal()

    expect(wrapper.text()).toContain('这是一句正文内容。')
    expect(wrapper.find('.self-check-warning').exists()).toBe(true)
    expect(wrapper.find('.self-check-warning').text()).toContain('未在参考资料中找到明确支撑')
  })

  it('未收到 self_check_warning 事件时不渲染提醒块', async () => {
    vi.mocked(openStream).mockReturnValue(streamOf([
      { eventType: 'chunk', data: { content: '这是一句正文内容。' } },
      { eventType: 'done', data: {} }
    ]) as never)
    const wrapper = mount(ChatPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await flushPromises()
    await wrapper.find('textarea').setValue('这句话有没有依据？')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    await drainReveal()

    expect(wrapper.find('.self-check-warning').exists()).toBe(false)
  })

  it('refusal 显示为正常检索不足状态，而不是模型回答', async () => {
    vi.mocked(openStream).mockReturnValue(streamOf([
      { eventType: 'refusal', data: { message: '未在当前知识库中检索到足够依据' } }
    ]) as never)
    const wrapper = mount(ChatPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await flushPromises() // 等待挂载时自动创建的会话(createSession)完成，否则 sessionId 未就绪、canSend 恒为 false
    await wrapper.find('textarea').setValue('不存在的问题')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('检索结果')
    expect(wrapper.text()).toContain('未在当前知识库中检索到足够依据')
  })

  it('回答含 Markdown 语法时渲染为格式化 HTML，而不是原样展示星号', async () => {
    vi.mocked(openStream).mockReturnValue(streamOf([
      { eventType: 'chunk', data: { content: '**加粗结论**：一切正常。' } },
      { eventType: 'done', data: {} }
    ]) as never)
    const wrapper = mount(ChatPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await flushPromises() // 等待挂载时自动创建的会话(createSession)完成，否则 sessionId 未就绪、canSend 恒为 false
    await wrapper.find('textarea').setValue('结果如何？')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    await drainReveal()

    const strong = wrapper.find('.message-content-markdown strong')
    expect(strong.exists()).toBe(true)
    expect(strong.text()).toBe('加粗结论')
    expect(wrapper.html()).not.toContain('**加粗结论**')
  })

  it('打字机效果：chunk 到达后不会瞬间整段出现，而是随时间推进逐步显现', async () => {
    vi.mocked(openStream).mockReturnValue(streamOf([
      { eventType: 'chunk', data: { content: '一段较长的回答内容用于验证节流展示效果' } },
      { eventType: 'done', data: {} }
    ]) as never)
    const wrapper = mount(ChatPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await flushPromises() // 等待挂载时自动创建的会话(createSession)完成，否则 sessionId 未就绪、canSend 恒为 false
    await wrapper.find('textarea').setValue('问题')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    // 数据已经全部到达（SSE 流已 done），但打字机只推进了很短时间，不应该整段出现。
    await vi.advanceTimersByTimeAsync(40)
    const partial = wrapper.text()
    expect(partial).not.toContain('一段较长的回答内容用于验证节流展示效果')

    // 推进足够时间后，应完整显现，且已经吐完的输入框应重新可用（sending=false）。
    await drainReveal()
    expect(wrapper.text()).toContain('一段较长的回答内容用于验证节流展示效果')
    expect(wrapper.find('textarea').attributes('disabled')).toBeFalsy()
  })

  it('回车直接发送', async () => {
    vi.mocked(openStream).mockReturnValue(streamOf([{ eventType: 'done', data: {} }]) as never)
    const wrapper = mount(ChatPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await flushPromises() // 等待挂载时自动创建的会话(createSession)完成，否则 sessionId 未就绪、canSend 恒为 false
    await wrapper.find('textarea').setValue('回车发送测试')
    await wrapper.find('textarea').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(openStream).toHaveBeenCalledWith(expect.objectContaining({
      body: { question: '回车发送测试', sessionId: 'session-1' }
    }))
  })

  it('shift+回车换行，不发送', async () => {
    const wrapper = mount(ChatPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await flushPromises() // 等待挂载时自动创建的会话(createSession)完成，否则 sessionId 未就绪、canSend 恒为 false
    await wrapper.find('textarea').setValue('第一行')
    await wrapper.find('textarea').trigger('keydown', { key: 'Enter', shiftKey: true })
    await flushPromises()
    expect(openStream).not.toHaveBeenCalled()
  })

  it('中文输入法候选词确认（isComposing）时的回车不触发发送', async () => {
    const wrapper = mount(ChatPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await flushPromises() // 等待挂载时自动创建的会话(createSession)完成，否则 sessionId 未就绪、canSend 恒为 false
    await wrapper.find('textarea').setValue('拼音候选中')
    await wrapper.find('textarea').trigger('keydown', { key: 'Enter', isComposing: true })
    await flushPromises()
    expect(openStream).not.toHaveBeenCalled()
  })

  it('localStorage 有记录的会话时，挂载时恢复历史消息而不是新建会话', async () => {
    localStorage.setItem('rag-kb:last-session:kb-1', 'session-remembered')
    vi.mocked(getSessionMessages).mockResolvedValue([
      { id: 'm1', role: 'user', content: '之前问过的问题', createdAt: '2026-07-15T00:00:00Z' },
      { id: 'm2', role: 'assistant', content: '之前的回答', createdAt: '2026-07-15T00:00:01Z' }
    ])

    const wrapper = mount(ChatPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(getSessionMessages).toHaveBeenCalledWith('', 'kb-1', 'session-remembered', expect.anything())
    expect(createSession).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('之前问过的问题')
    expect(wrapper.text()).toContain('之前的回答')
  })

  it('恢复历史会话后，带 citations 的消息点击正文里的 [资料N] 也能弹出抽屉', async () => {
    localStorage.setItem('rag-kb:last-session:kb-1', 'session-remembered')
    vi.mocked(getSessionMessages).mockResolvedValue([
      { id: 'm1', role: 'user', content: '如何排查启动失败？', createdAt: '2026-07-15T00:00:00Z' },
      {
        id: 'm2', role: 'assistant', content: '请检查数据库连接 [资料1]。', createdAt: '2026-07-15T00:00:01Z',
        citations: [{ documentId: 'd1', documentName: '部署说明.md', headingPath: ['部署'], snippet: '检查数据库连接的详细说明', pageNo: 2, lineStart: 4, lineEnd: 5, score: 0.91 }]
      }
    ])

    const wrapper = mount(ChatPanel, {
      props: { kbId: 'kb-1' },
      global: { plugins: [ElementPlus] },
      attachTo: document.body
    })
    await flushPromises()

    const ref = wrapper.find('.citation-ref')
    expect(ref.exists()).toBe(true)
    await ref.trigger('click')
    await flushPromises()

    const drawer = document.querySelector('[data-testid="citation-drawer"]')
    expect(drawer).not.toBeNull()
    expect(drawer?.textContent).toContain('部署说明.md')

    wrapper.unmount()
  })

  it('localStorage 记录的会话已失效（404）时退回空白新对话，且不提前创建会话', async () => {
    localStorage.setItem('rag-kb:last-session:kb-1', 'session-deleted')
    vi.mocked(getSessionMessages).mockRejectedValue(new Error('HTTP 404 Not Found'))

    const wrapper = mount(ChatPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(getSessionMessages).toHaveBeenCalledWith('', 'kb-1', 'session-deleted', expect.anything())
    // 懒创建：恢复失败只回到空白状态，不应该在这里就调用创建会话接口。
    expect(createSession).not.toHaveBeenCalled()
    // 恢复失败后应能正常提问，不应停留在"会话未就绪"状态；真正发消息时才懒创建会话。
    vi.mocked(openStream).mockReturnValue(streamOf([{ eventType: 'done', data: {} }]) as never)
    await wrapper.find('textarea').setValue('恢复失败后继续提问')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(createSession).toHaveBeenCalledWith('', 'kb-1', expect.anything())
    expect(localStorage.getItem('rag-kb:last-session:kb-1')).toBe('session-1')
    expect(openStream).toHaveBeenCalledWith(expect.objectContaining({
      body: { question: '恢复失败后继续提问', sessionId: 'session-1' }
    }))
  })

  it('没有 localStorage 记录时不提前创建会话；只有真正发送消息才懒创建', async () => {
    const wrapper = mount(ChatPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(createSession).not.toHaveBeenCalled()
    expect(localStorage.getItem('rag-kb:last-session:kb-1')).toBeNull()
    expect(wrapper.findComponent({ name: 'ChatHistorySidebar' }).exists()).toBe(true)

    vi.mocked(openStream).mockReturnValue(streamOf([{ eventType: 'done', data: {} }]) as never)
    await wrapper.find('textarea').setValue('第一条真实消息')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(createSession).toHaveBeenCalledWith('', 'kb-1', expect.anything())
    expect(localStorage.getItem('rag-kb:last-session:kb-1')).toBe('session-1')
  })

  it('新建对话按钮/删除当前会话后回到空白状态，不调用创建会话接口', async () => {
    localStorage.setItem('rag-kb:last-session:kb-1', 'session-remembered')
    vi.mocked(getSessionMessages).mockResolvedValue([
      { id: 'm1', role: 'user', content: '之前问过的问题', createdAt: '2026-07-15T00:00:00Z' }
    ])
    const wrapper = mount(ChatPanel, { props: { kbId: 'kb-1' }, global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(wrapper.text()).toContain('之前问过的问题')
    vi.mocked(createSession).mockClear()

    const sidebar = wrapper.findComponent({ name: 'ChatHistorySidebar' })
    await sidebar.vm.$emit('create')
    await flushPromises()

    expect(wrapper.text()).not.toContain('之前问过的问题')
    expect(createSession).not.toHaveBeenCalled()
  })
})
