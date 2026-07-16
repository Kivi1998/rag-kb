# 知识库右键菜单 + 独立技术文档页面 + 侧边栏图标调整

日期：2026-07-16
分支：`feat/citation-drawer-and-collapsible-docs`（在已有分支上继续，不新开分支）

## 背景

上一版改动（PR #22 未合并部分）把"技术文档"（`DocumentPanel`）做成了工作区内可折叠的侧边面板，
默认收起、点开关按钮展开。用户体验后决定推翻这个方案，改为：

1. 知识库列表的重命名/删除操作从"hover 才出现的按钮"改成右键菜单，同一个菜单里再加一个跳转到
   独立"技术文档"页面的入口。
2. 工作区（`KbWorkspaceView.vue`）里完全去掉技术文档面板/折叠开关，问答区占满整个主区域；
   技术文档改成独立路由页面，通过右键菜单跳转，用于查看和上传/处理文档。
3. 对话历史侧边栏（`ChatHistorySidebar.vue`）现在的展开/收起图标（左右箭头）换成类似 Claude 官方
   UI 里"切换边栏"的图标（圆角矩形 + 竖线分割），Element Plus 图标库没有现成的完全匹配图标，
   自己写一个小 SVG 组件还原。

三块改动都是纯前端 UI 重构，互不依赖、不涉及后端接口变化，可以放在一个设计里一次写完，
实现时按文件逐个推进。

## 架构

### 1. 知识库右键菜单（`KbSidebar.vue`）

用 Element Plus `<el-dropdown trigger="contextmenu">` 包住每个知识库条目（`.kb-item`），
`#dropdown` 插槽放 `<el-dropdown-menu>`，三个 `<el-dropdown-item>`：

- `command="rename"`，文案"重命名" → 复用现有 `openRenameDialog(kb)`
- `command="delete"`，文案"删除" → 复用现有 `handleDelete(kb)`
- `command="documents"`，文案"技术文档"（`divided` 属性与前两项隔开）
  → `router.push({ name: 'kb-documents', params: { kbId: kb.id } })`

原来 hover 才显示的 `Edit`/`Delete` 图标按钮（`.kb-actions`）整块删除，`el-dropdown` 的
`trigger="contextmenu"` 内部会自己 `preventDefault()` 浏览器原生右键菜单，不需要手动处理。
左键单击 `<el-menu-item>` 的 `@select` 行为不变，仍然是切换 `kbStore.selectedKbId` 进问答。

### 2. 独立技术文档页面

**路由**（`frontend/src/router/index.ts`）新增：

```
{
  path: '/kb/:kbId/documents',
  name: 'kb-documents',
  component: () => import('@/views/DocumentsView.vue'),
  meta: { requiresAuth: true }
}
```

**`DocumentsView.vue`**（新建，布局参照 `KbWorkspaceView.vue` 的外壳）：

- 左侧保留 `<KbSidebar />`（与工作区一致，方便直接切换到另一个知识库的文档页，不用先返回问答页）。
- 顶部标题区：知识库名称 + "技术文档" 副标题 + 一个"← 返回问答"链接（`router.push({ name: 'kb' })`，
  不用 `router.back()`，因为直接输入 URL/刷新页面时没有可回退的历史记录）。
- 主区域直接渲染 `<DocumentPanel :kb-id="kbId" />`，`DocumentPanel.vue` 内部逻辑完全不改。
- `onMounted`/路由参数变化时：若 `route.params.kbId` 在 `kbStore.kbs` 里存在，
  同步 `kbStore.selectedKbId = kbId`（保持左侧列表高亮、返回问答页时还是这个知识库）；
  若找不到（KB 已删除或 URL 是坏的），展示 `<el-empty description="该知识库不存在或已删除">`
  + 返回 `/kb` 的链接，不渲染 `DocumentPanel`。

### 3. 工作区去掉技术文档面板（`KbWorkspaceView.vue`）

删除 `documentPanelExpanded` ref、`DocumentPanel` 的 import 和渲染、折叠按钮及其
`ArrowLeftBold`/`ArrowRightBold` 相关代码，以及 `.workspace-panels`/`.document-panel-slot`/
`.document-toggle-btn` 相关 CSS（这些都是本次要撤销的上一版改动）。`<ChatPanel>` 直接占满
`main-content` 下方剩余空间，不再需要两栏 grid。

### 4. 对话历史侧边栏图标（`ChatHistorySidebar.vue`）

新增一个小组件 `frontend/src/components/icons/SidebarToggleIcon.vue`：内联 SVG，
还原截图里那个圆角矩形外框 + 一条竖线把左侧分割出一小块的图标（24×24 viewBox，
`currentColor` 描边，方便跟随 `.toggle-btn` 的文字颜色变化）。替换模板里的
`<el-icon><component :is="expanded ? ArrowLeftBold : ArrowRightBold" /></el-icon>`
为 `<SidebarToggleIcon />`——展开和收起用同一个图标（跟 Claude 原版一致，不是两个图标切换），
`aria-label` 展开/收起的文字提示保持不变。

## 数据流与错误处理

- `kbStore.selectedKbId` 仍是唯一的"当前知识库"状态源；`DocumentsView` 用路由参数同步一次，
  两个页面（问答工作区、技术文档页）来回切换时状态保持一致。
- 非法/已删除知识库的 `:kbId` 参数：显示空状态 + 返回链接，不崩溃、不发起无意义的
  `DocumentPanel` 请求（`DocumentPanel` 组件只在 kbId 校验通过后才渲染）。
- 重命名/删除的确认弹窗（`ElMessageBox.confirm`）、成功/失败提示（`ElMessage`）逻辑完全不变，
  只是触发入口从按钮点击换成右键菜单的 `@command` 事件处理。

## 测试

- `KbSidebar.test.ts`（新建）：右键触发 contextmenu 弹出菜单；三个 command 分别触发
  重命名弹窗打开、删除确认流程（复用 `ElMessageBox.confirm` mock 模式）、路由跳转到
  `kb-documents` 且带正确 `kbId` 参数。
- `DocumentsView.test.ts`（新建）：渲染出 `DocumentPanel`；"返回问答"链接跳转到 `/kb`；
  不存在的 `kbId` 展示空状态且不渲染 `DocumentPanel`。
- `ChatHistorySidebar.test.ts`：更新图标相关断言（若原来有专门检查 icon 类型的用例）。
- `router.test.ts`：补一条 `kb-documents` 路由需要登录（`requiresAuth`）的用例，与现有其他
  受保护路由的测试模式一致。
- `KbWorkspaceView.vue` 目前没有测试文件，本次简化后不强制补。

## Non-Goals

- 不改动后端任何接口（重命名/删除/文档上传的 API 都复用现有的）。
- 不改动 `DocumentPanel.vue` 内部逻辑（上传队列、轮询、分页等），只是换了个挂载位置。
- 不引入通用的"右键菜单"抽象组件——目前只有知识库列表这一处需要，YAGNI，不做过度设计。
