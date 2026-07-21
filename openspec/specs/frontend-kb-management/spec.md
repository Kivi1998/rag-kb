# frontend-kb-management Specification

## Purpose

知识库侧边栏导航——220px 固定宽度侧边栏(`KbSidebar.vue`)承载当前组织的知识库列表、创建入口,以及基于右键菜单(`el-dropdown trigger="contextmenu"`)的重命名/删除/跳转技术文档操作;左键选中 KB 只驱动主区域的问答面板(`ChatPanel`),不再内嵌技术文档 Tab——技术文档管理已迁移到独立路由 `/kb/:kbId/documents`(见 frontend-document-management 规格)。

## Requirements
### Requirement: 知识库导航侧边栏

系统 SHALL 在左侧 220px 固定宽度侧边栏(`el-menu`)展示当前用户所在组织的知识库列表,MUST 包含"新建知识库"入口(标题栏 `+` 圆形按钮)。选中 KB SHALL 高亮显示,切换 KB 时主内容区的问答面板 MUST 同步更新为该 KB 的会话。

#### Scenario: 初始加载

- **WHEN** 用户进入 `/kb` 页面
- **THEN** 自动拉取 `GET /api/v1/knowledge-bases` 并渲染列表;若列表为空,主区域显示"请先选择或创建知识库"引导

#### Scenario: 选择知识库

- **WHEN** 用户左键点击侧边栏某个 KB(`el-menu` 的 `select` 事件)
- **THEN** 该 KB 在侧边栏高亮,主内容区的问答面板(`ChatPanel`)切换为该 KB 的对话;技术文档不在此处展示,需通过右键菜单单独进入

### Requirement: 创建知识库

用户 SHALL 通过弹窗(`el-dialog` + `el-form`)输入知识库名称创建新 KB。当前实现未绑定 `el-form` 校验规则,名称留空时点击确认按钮为静默无操作(不发起请求,也不展示表单错误提示),而非表单级校验报错。

#### Scenario: 创建成功

- **WHEN** 用户填写名称并点击确认
- **THEN** 调用 `POST /api/v1/knowledge-bases`,成功后新 KB 出现在侧边栏并自动选中

#### Scenario: 名称为空提交

- **WHEN** 用户未填写名称(或仅输入空白字符)点击确认
- **THEN** 点击处理函数直接返回,不发起创建请求,弹窗保持打开且不展示任何错误提示

### Requirement: 重命名知识库

用户 SHALL 通过右键菜单(`trigger="contextmenu"`)触发弹窗对已有 KB 进行重命名,弹窗 MUST 回填当前名称。名称留空时的行为与创建知识库一致(静默无操作,不发起请求)。

#### Scenario: 重命名成功

- **WHEN** 用户修改名称并确认
- **THEN** 调用 `PATCH /api/v1/knowledge-bases/{id}`,成功后侧边栏名称更新

### Requirement: 删除知识库

用户 SHALL 通过右键菜单进入删除项,经二次确认(`ElMessageBox.confirm`)删除 KB。响应经统一 axios 拦截器解包:后端 `code=0` 时拦截器直接返回内层 `data`(此时为字符串,如 `"已删除"`),后端 `code=202` 时拦截器返回 `{ code: 202, message }`;前端 MUST 用返回值是否为 `{ code: 202 }` 形状来区分"已完全删除"和"标记待清理",不存在、也不应依赖任何 `data.deleted` 布尔字段。

> **说明:** `code=202`(待清理)分支是 RAGFlow 时代"dataset 删除失败进对账"机制的历史遗留防御性代码,当前后端 `KnowledgeBaseService.delete()` 已不再依赖任何外部资源,恒定完全删除成功,该分支在当前实现下不会被触发,前端相应的"待清理"标签逻辑予以保留但实际不会展示。

#### Scenario: 删除成功

- **WHEN** 后端返回 `code=0`(拦截器解包后得到字符串型 `data`,非 `{ code: 202 }` 形状)
- **THEN** 从侧边栏移除该 KB,若为当前选中则自动切换到列表中第一个 KB(无 KB 时取消选中)

#### Scenario: 删除标记为待清理(历史遗留分支)

- **WHEN** 后端返回 `code=202`
- **THEN** 该 KB 在侧边栏显示"待清理"标签,不从列表移除,提示用户联系管理员
