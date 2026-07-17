import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'

const push = vi.fn()
const route = { params: { kbId: 'kb-1' } }
vi.mock('vue-router', () => ({ useRouter: () => ({ push }), useRoute: () => route }))

vi.mock('@/components/KbSidebar.vue', () => ({ default: { template: '<div>KbSidebar</div>' } }))
vi.mock('@/components/DocumentPanel.vue', () => ({
  default: { props: ['kbId'], template: '<div class="document-panel-stub">DocumentPanel {{ kbId }}</div>' }
}))
vi.mock('@/api/kbApi', () => ({ kbApi: { list: vi.fn() } }))

import DocumentsView from '@/views/DocumentsView.vue'
import { useKbStore } from '@/stores/kbStore'

describe('DocumentsView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    route.params.kbId = 'kb-1'
  })

  it('已知 kbId 渲染 DocumentPanel 并同步 kbStore.selectedKbId', async () => {
    const store = useKbStore()
    store.kbs = [{ id: 'kb-1', name: '本科毕设', status: 'ACTIVE', createdAt: '2026-01-01' }] as any

    const wrapper = mount(DocumentsView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(wrapper.find('.document-panel-stub').text()).toContain('kb-1')
    expect(wrapper.text()).toContain('本科毕设')
    expect(store.selectedKbId).toBe('kb-1')
  })

  it('点击"返回问答"跳转到 kb 路由', async () => {
    const store = useKbStore()
    store.kbs = [{ id: 'kb-1', name: '本科毕设', status: 'ACTIVE', createdAt: '2026-01-01' }] as any

    const wrapper = mount(DocumentsView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    await wrapper.find('.back-link').trigger('click')

    expect(push).toHaveBeenCalledWith({ name: 'kb' })
  })

  it('kbId 不存在（已删除或坏链接）时展示空状态，不渲染 DocumentPanel', async () => {
    const store = useKbStore()
    store.kbs = [{ id: 'kb-other', name: '别的知识库', status: 'ACTIVE', createdAt: '2026-01-01' }] as any
    route.params.kbId = 'kb-missing'

    const wrapper = mount(DocumentsView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(wrapper.find('.document-panel-stub').exists()).toBe(false)
    expect(wrapper.text()).toContain('该知识库不存在或已删除')
  })
})
