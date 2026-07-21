import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('element-plus', async () => {
  const actual = await vi.importActual<typeof import('element-plus')>('element-plus')
  return { ...actual, ElMessage: { success: vi.fn(), error: vi.fn() }, ElMessageBox: { confirm: vi.fn() } }
})
vi.mock('@/api/queryApi', () => ({
  listSessions: vi.fn(),
  deleteSession: vi.fn()
}))

import ChatHistorySidebar from '@/components/ChatHistorySidebar.vue'
import { deleteSession, listSessions } from '@/api/queryApi'
import { ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/authStore'

const sessions = [
  { sessionId: 's-1', title: '最近的对话', lastActiveAt: '2026-07-15T02:00:00Z' },
  { sessionId: 's-2', title: null, lastActiveAt: '2026-07-15T01:00:00Z' }
]

describe('ChatHistorySidebar', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(listSessions).mockResolvedValue(sessions)
    const auth = useAuthStore()
    auth.token = 'token-1'
    auth.orgId = 'org-1'
  })

  it('expanded=false 时不拉取列表，也不渲染面板', () => {
    const wrapper = mount(ChatHistorySidebar, {
      props: { kbId: 'kb-1', activeSessionId: null, expanded: false },
      global: { plugins: [ElementPlus] }
    })
    expect(listSessions).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="chat-history-sidebar"]').exists()).toBe(false)
  })

  it('expanded 从 false 变为 true 时拉取并渲染历史会话列表，空标题显示兜底文案', async () => {
    const wrapper = mount(ChatHistorySidebar, {
      props: { kbId: 'kb-1', activeSessionId: null, expanded: false },
      global: { plugins: [ElementPlus] }
    })

    await wrapper.setProps({ expanded: true })
    await flushPromises()

    expect(listSessions).toHaveBeenCalledWith('', 'kb-1', expect.anything())
    expect(wrapper.text()).toContain('最近的对话')
    expect(wrapper.text()).toContain('新对话') // s-2 的空标题兜底文案
  })

  it('面板保持展开时切换 kbId 也要重新拉取该知识库的会话列表', async () => {
    const wrapper = mount(ChatHistorySidebar, {
      props: { kbId: 'kb-1', activeSessionId: null, expanded: true },
      global: { plugins: [ElementPlus] }
    })
    await flushPromises()
    expect(listSessions).toHaveBeenNthCalledWith(1, '', 'kb-1', expect.anything())
    vi.mocked(listSessions).mockClear()

    // expanded 全程保持 true 不变，只切换 kbId：不能因为 expanded 没变就漏刷新，
    // 否则历史列表会停留在切换前那个知识库的内容上。
    await wrapper.setProps({ kbId: 'kb-2' })
    await flushPromises()

    expect(listSessions).toHaveBeenCalledWith('', 'kb-2', expect.anything())
  })

  it('点击历史项触发 select 事件', async () => {
    const wrapper = mount(ChatHistorySidebar, {
      props: { kbId: 'kb-1', activeSessionId: null, expanded: true },
      global: { plugins: [ElementPlus] }
    })
    await flushPromises()

    await wrapper.findAll('.session-item')[0].trigger('click')

    expect(wrapper.emitted('select')).toEqual([['s-1']])
  })

  it('点击新建对话触发 create 事件并刷新列表', async () => {
    const wrapper = mount(ChatHistorySidebar, {
      props: { kbId: 'kb-1', activeSessionId: null, expanded: true },
      global: { plugins: [ElementPlus] }
    })
    await flushPromises()
    vi.mocked(listSessions).mockClear()

    await wrapper.find('.panel-header .el-button').trigger('click')
    await flushPromises()

    expect(wrapper.emitted('create')).toHaveLength(1)
    expect(listSessions).toHaveBeenCalledTimes(1)
  })

  it('确认删除后调用删除接口、从列表移除并触发 deleted 事件', async () => {
    vi.mocked(ElMessageBox.confirm).mockResolvedValue('confirm' as never)
    vi.mocked(deleteSession).mockResolvedValue()
    const wrapper = mount(ChatHistorySidebar, {
      props: { kbId: 'kb-1', activeSessionId: null, expanded: true },
      global: { plugins: [ElementPlus] }
    })
    await flushPromises()

    await wrapper.find('.session-item .delete-icon').trigger('click')
    await flushPromises()

    expect(deleteSession).toHaveBeenCalledWith('', 'kb-1', 's-1', expect.anything())
    expect(wrapper.emitted('deleted')).toEqual([['s-1']])
    expect(wrapper.text()).not.toContain('最近的对话')
  })

  it('取消确认弹窗时不调用删除接口', async () => {
    vi.mocked(ElMessageBox.confirm).mockRejectedValue('cancel' as never)
    const wrapper = mount(ChatHistorySidebar, {
      props: { kbId: 'kb-1', activeSessionId: null, expanded: true },
      global: { plugins: [ElementPlus] }
    })
    await flushPromises()

    await wrapper.find('.session-item .delete-icon').trigger('click')
    await flushPromises()

    expect(deleteSession).not.toHaveBeenCalled()
    expect(wrapper.emitted('deleted')).toBeUndefined()
  })
})
