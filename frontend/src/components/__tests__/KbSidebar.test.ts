import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'

const push = vi.fn()
vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }))

vi.mock('element-plus', async () => {
  const actual = await vi.importActual<typeof import('element-plus')>('element-plus')
  return { ...actual, ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() }, ElMessageBox: { confirm: vi.fn() } }
})

vi.mock('@/api/kbApi', () => ({
  kbApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() }
}))

import KbSidebar from '@/components/KbSidebar.vue'
import { useKbStore } from '@/stores/kbStore'
import { ElMessageBox } from 'element-plus'

const kbs = [{ id: 'kb-1', name: '本科毕设', status: 'ACTIVE', createdAt: '2026-01-01' }]

describe('KbSidebar 右键菜单', () => {
  let wrapper: VueWrapper<any> | undefined

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  // el-dropdown-menu/el-dialog 都是 teleport 到 document.body 渲染的，不在 wrapper 的 DOM
  // 子树内；不 unmount 的话上一个用例的菜单/弹窗会残留在 body 里，干扰下一个用例的查询。
  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
  })

  function mountWithKbs() {
    wrapper = mount(KbSidebar, { global: { plugins: [ElementPlus] }, attachTo: document.body })
    const store = useKbStore()
    store.kbs = kbs as any
    return wrapper
  }

  async function openContextMenu(target: VueWrapper<any>) {
    await target.find('.kb-item').trigger('contextmenu')
    await flushPromises()
  }

  function findMenuItem(label: string) {
    const items = Array.from(document.querySelectorAll('.el-dropdown-menu__item'))
    return items.find((el) => el.textContent?.trim() === label) as HTMLElement | undefined
  }

  it('右键单击知识库条目弹出菜单，包含重命名/删除/技术文档三项', async () => {
    const target = mountWithKbs()
    await target.vm.$nextTick()
    await openContextMenu(target)

    const items = document.querySelectorAll('.el-dropdown-menu__item')
    const labels = Array.from(items).map((el) => el.textContent?.trim())
    expect(labels).toEqual(['重命名', '删除', '技术文档'])
  })

  it('点击"重命名"打开重命名弹窗并预填当前名称', async () => {
    const target = mountWithKbs()
    await target.vm.$nextTick()
    await openContextMenu(target)
    findMenuItem('重命名')?.click()
    await flushPromises()

    expect(document.body.textContent).toContain('重命名知识库')
    expect((target.findComponent({ name: 'ElInput' }).vm as any).modelValue).toBe('本科毕设')
  })

  it('点击"删除"并确认后调用删除接口', async () => {
    vi.mocked(ElMessageBox.confirm).mockResolvedValue('confirm' as never)
    const target = mountWithKbs()
    const store = useKbStore()
    const deleteSpy = vi.spyOn(store, 'deleteKb').mockResolvedValue()
    await target.vm.$nextTick()
    await openContextMenu(target)
    findMenuItem('删除')?.click()
    await flushPromises()

    expect(deleteSpy).toHaveBeenCalledWith('kb-1')
  })

  it('点击"技术文档"跳转到 kb-documents 路由并带上 kbId', async () => {
    const target = mountWithKbs()
    await target.vm.$nextTick()
    await openContextMenu(target)
    findMenuItem('技术文档')?.click()
    await flushPromises()

    expect(push).toHaveBeenCalledWith({ name: 'kb-documents', params: { kbId: 'kb-1' } })
  })
})
