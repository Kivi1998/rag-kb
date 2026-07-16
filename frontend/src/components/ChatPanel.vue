<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { CircleClose, Promotion } from '@element-plus/icons-vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { useAuthStore } from '@/stores/authStore'
import { createSession, getSessionMessages, openStream, queryStreamUrl } from '@/api/queryApi'
import ChatHistorySidebar from '@/components/ChatHistorySidebar.vue'
import type { Citation } from '@/types/citation'
import type { Message, QueryEvent } from '@/types/query'

/** 打字机式节流展示：每 tick 吐出的字符数与间隔。上游 LLM（DeepSeek 等）自身的
 * SSE 推送就是一批一批到达的（同一段回答可能有 50%+ 内容挤在最后 0.2s 内到达，
 * 不受我们控制），如果收到多少就立刻整段渲染多少，视觉上仍会"一股脑蹦出来"。
 * 这里把"数据到达"和"文字显现"解耦：到达的内容先进缓冲区，再由定时器匀速吐出。 */
const REVEAL_INTERVAL_MS = 20
const REVEAL_CHARS_PER_TICK = 2

const props = defineProps<{ kbId: string }>()
const authStore = useAuthStore()
const question = ref('')
const messages = ref<Message[]>([])
const sending = ref(false)
const streamAbort = ref<AbortController | null>(null)
const transcript = ref<HTMLElement | null>(null)
/** 当前知识库的活跃会话标识。 */
const sessionId = ref<string | null>(null)
const sessionReady = ref(false)
const historySidebar = ref<InstanceType<typeof ChatHistorySidebar> | null>(null)
/** 引用来源不再默认全部展示在回答下方，点击正文里的 [资料N] 才在右侧弹出对应这一条。 */
const citationDrawerVisible = ref(false)
const selectedCitation = ref<Citation | null>(null)
const selectedCitationIndex = ref<number | null>(null)

/** localStorage 记录每个知识库最后活跃的会话，供刷新/重新进入时恢复历史，而不是总是新建。 */
function lastSessionStorageKey(kbId: string): string {
  return `rag-kb:last-session:${kbId}`
}

function readLastSessionId(kbId: string): string | null {
  try {
    return localStorage.getItem(lastSessionStorageKey(kbId))
  } catch {
    return null // 隐私模式等场景 localStorage 不可用，退化为总是新建，不阻断使用
  }
}

function writeLastSessionId(kbId: string, id: string) {
  try {
    localStorage.setItem(lastSessionStorageKey(kbId), id)
  } catch {
    // 同上，写入失败不影响当前会话正常使用
  }
}

/** LLM 回答含 Markdown 语法（**加粗**、列表、代码块等），此前直接文本插值导致
 * 语法符号原样显示。仅对话回答需要渲染；用户自己打的话按纯文本展示，避免用户
 * 输入里的 `*`/`#` 被意外解释成 Markdown。渲染结果必须过 DOMPurify 净化后才能
 * 用 v-html 注入，防止检索到的文档内容里混入的 HTML/脚本片段被当作真实标签执行。
 *
 * 正文里的 `[资料N]` 在 markdown 解析前先转成可点击的 `<sup>`（data-ref 记录编号），
 * 点击后由 handleCitationClick 在右侧弹出该条引用；DOMPurify 默认允许 class/data-*
 * 属性通过，不需要额外放宽白名单。 */
function renderMarkdown(content: string): string {
  const withCitationRefs = content.replace(
    /\[资料(\d+)\]/g,
    '<sup class="citation-ref" data-ref="$1" role="button" tabindex="0">[$1]</sup>'
  )
  const html = marked.parse(withCitationRefs, { async: false, breaks: true }) as string
  return DOMPurify.sanitize(html)
}

/** 点击正文里的 `[资料N]`（渲染为 `.citation-ref`）时，从这一条消息的 citations 里
 * 取出对应的第 N 条，在右侧抽屉里展示来源文件/定位/原文片段；点击其他内容不处理。 */
function handleCitationClick(event: MouseEvent, message: Message) {
  const target = (event.target as HTMLElement | null)?.closest('.citation-ref')
  if (!target) return
  const ref = target.getAttribute('data-ref')
  if (!ref) return
  const index = Number.parseInt(ref, 10)
  const citation = message.citations?.[index - 1]
  if (!citation) return
  selectedCitation.value = citation
  selectedCitationIndex.value = index
  citationDrawerVisible.value = true
}

const canSend = computed(() => !!props.kbId && !!question.value.trim() && !sending.value && sessionReady.value)

/** 引用抽屉展示的是某一条历史消息的引用，切换/重置会话后 messages 已经不是那一条了，
 * 抽屉若还开着会显示跟当前可见对话对不上的内容，因此每次切换会话前先关掉。 */
function closeCitationDrawer() {
  citationDrawerVisible.value = false
  selectedCitation.value = null
  selectedCitationIndex.value = null
}

/** 切换到某个已存在的会话：拉取其历史消息并 hydrate；供"刷新恢复"与"点击历史列表项"共用。 */
async function switchToSession(id: string) {
  const history = await getSessionMessages('', props.kbId, id, headers())
  closeCitationDrawer()
  sessionId.value = id
  messages.value = history
  sessionReady.value = true
  writeLastSessionId(props.kbId, id)
}

/**
 * 重置为"尚未创建会话"的空白状态，不调用创建会话接口——真正的 chat_session 记录推迟到
 * 用户实际发送第一条消息时才在 {@link ask} 里懒创建。这样每次挂载/切知识库/点"新建对话"
 * 都不会在 Postgres 里留下从未真正使用过的空会话，历史列表也就不会被这些空占位淤积。
 */
function resetToNewConversation() {
  closeCitationDrawer()
  sessionId.value = null
  messages.value = []
  sessionReady.value = true
}

/**
 * 进入知识库/刷新页面时：优先尝试恢复 localStorage 记录的上一个会话（含历史消息），
 * 而不是总是新建——这是"F5 刷新回到刚才那个对话"的关键；恢复失败（如该会话已被
 * 删除，接口返回 404）时退回到空白新对话状态，不阻断使用。
 */
async function initializeSession() {
  sessionReady.value = false
  sessionId.value = null
  messages.value = []
  if (!props.kbId) return
  const remembered = readLastSessionId(props.kbId)
  if (remembered) {
    try {
      await switchToSession(remembered)
      return
    } catch (error) {
      console.warn('恢复历史会话失败，改为新建会话', error)
    }
  }
  resetToNewConversation()
}

async function handleSelectSession(id: string) {
  if (id === sessionId.value || sending.value) return
  cancel()
  try {
    await switchToSession(id)
  } catch (error) {
    console.error('切换历史会话失败', error)
  }
}

function handleCreateFromSidebar() {
  cancel()
  resetToNewConversation()
}

function handleSessionDeleted(deletedId: string) {
  if (deletedId === sessionId.value) {
    cancel()
    resetToNewConversation()
  }
}

/** 网络流可能已经结束，但打字机还在把缓冲区剩余内容匀速吐出——这段时间点
 * "取消生成"，仅 abort 网络请求毫无意义（请求早就完成了）。ask() 内部把
 * "立即停止吐字"的回调注册到这里，供 cancel() 调用。 */
let stopRevealCallback: (() => void) | undefined

function headers() {
  const result: Record<string, string> = {}
  if (authStore.token) result.Authorization = `Bearer ${authStore.token}`
  if (authStore.orgId) result['X-Org-Id'] = authStore.orgId
  return result
}

function createAssistantMessage(): Message {
  return { id: crypto.randomUUID(), role: 'assistant', content: '', citations: [], createdAt: new Date().toISOString() }
}

async function ask() {
  const text = question.value.trim()
  if (!text || sending.value) return
  // 懒创建：只有真正发送第一条消息时才建会话，避免历史列表里出现从未使用过的空会话。
  if (!sessionId.value) {
    try {
      const newId = await createSession('', props.kbId, headers())
      sessionId.value = newId
      writeLastSessionId(props.kbId, newId)
    } catch (error) {
      console.error('创建会话失败', error)
      return
    }
  }
  const currentSessionId = sessionId.value
  if (!currentSessionId) return // 理论上不会发生，仅用于类型收窄
  const userMessage: Message = { id: crypto.randomUUID(), role: 'user', content: text, createdAt: new Date().toISOString() }
  const assistantMessage = createAssistantMessage()
  messages.value.push(userMessage, assistantMessage)
  question.value = ''
  sending.value = true

  // 待吐出的缓冲文本；由 revealTimer 匀速搬进 assistantMessage.content。
  let pending = ''
  let revealTimer: ReturnType<typeof setInterval> | undefined
  let networkDone = false

  function stopRevealing() {
    if (revealTimer) {
      clearInterval(revealTimer)
      revealTimer = undefined
    }
  }
  /** 网络流已结束且缓冲区已吐完，才算真正生成完毕——即使 SSE 已经 done，
   * 只要屏幕上文字还没显现完，仍应保持"生成中"状态，不能让输入框提前解禁。 */
  function finishIfDrained() {
    if (networkDone && !pending) {
      stopRevealing()
      sending.value = false
      streamAbort.value = null
      stopRevealCallback = undefined
    }
  }
  function ensureRevealing() {
    if (revealTimer) return
    revealTimer = setInterval(() => {
      if (pending) {
        assistantMessage.content += pending.slice(0, REVEAL_CHARS_PER_TICK)
        pending = pending.slice(REVEAL_CHARS_PER_TICK)
        void scrollToBottom()
      }
      finishIfDrained()
    }, REVEAL_INTERVAL_MS)
  }
  stopRevealCallback = () => {
    stopRevealing()
    pending = ''
    sending.value = false
    streamAbort.value = null
    stopRevealCallback = undefined
  }

  const controller = new AbortController()
  streamAbort.value = controller
  try {
    for await (const event of openStream({
      url: queryStreamUrl('', props.kbId),
      body: { question: text, sessionId: currentSessionId }, headers: headers(), signal: controller.signal
    })) {
      if (event.eventType === 'chunk') {
        pending += event.data.content
        ensureRevealing()
      } else {
        applyEvent(assistantMessage, event)
      }
      if (event.eventType === 'done' || event.eventType === 'error' || event.eventType === 'refusal') break
    }
  } catch (error) {
    if ((error as Error).name !== 'AbortError') {
      pending = ''
      assistantMessage.role = 'error'
      assistantMessage.content = '连接问答服务失败，请稍后重试。'
    } else if (!assistantMessage.content && !pending) {
      assistantMessage.role = 'error'
      assistantMessage.content = '已取消本次问答。'
    } else {
      // 已经开始显现内容后用户点了取消：把缓冲区剩余内容直接展示完，不留半截字。
      assistantMessage.content += pending
      pending = ''
    }
  } finally {
    networkDone = true
    if (pending) {
      ensureRevealing()
    } else {
      stopRevealing()
      sending.value = false
      streamAbort.value = null
      stopRevealCallback = undefined
    }
    await scrollToBottom()
    // 本轮问答可能刚生成了会话标题（首轮）或更新了最后活跃时间，刷新一下侧边栏列表。
    void historySidebar.value?.refresh()
  }
}

function applyEvent(message: Message, event: QueryEvent) {
  switch (event.eventType) {
    case 'chunk': break // chunk 事件在 ask() 里单独走缓冲/节流逻辑，不会走到这里
    case 'source': message.citations = [...(message.citations || []), event.data.citation]; break
    case 'refusal':
      message.role = 'refusal'
      message.content = event.data.message
      break
    case 'self_check_warning': message.selfCheckWarning = event.data.message; break
    case 'error':
      message.role = 'error'
      message.content = event.data.message
      break
    case 'done': break
  }
}

function cancel() {
  streamAbort.value?.abort()
  // 网络流可能已经结束、只是打字机还在吐字：单纯 abort 请求不会停止吐字，
  // 需要显式调用 ask() 注册的回调立即停止。
  stopRevealCallback?.()
}

/**
 * Enter 直接发送；Shift+Enter 换行（保留 textarea 默认行为，不拦截）。
 * `isComposing` 排除中文输入法确认候选词时误触发的 Enter（拼音选字按 Enter
 * 提交候选，不代表用户想发送消息），是中文输入场景下常见的一个坑。
 */
function handleComposerKeydown(event: Event) {
  if (!(event instanceof KeyboardEvent)) return
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  ask()
}

async function scrollToBottom() {
  await nextTick()
  if (transcript.value) transcript.value.scrollTop = transcript.value.scrollHeight
}

function citationLocation(citation: Citation) {
  const parts = [citation.headingPath.join(' / ')]
  if (citation.pageNo !== null) parts.push(`第 ${citation.pageNo} 页`)
  if (citation.lineStart !== null) parts.push(`第 ${citation.lineStart}${citation.lineEnd === null ? '' : `-${citation.lineEnd}`} 行`)
  return parts.filter(Boolean).join(' · ')
}

watch(
  () => props.kbId,
  () => {
    question.value = ''
    cancel()
    void initializeSession()
  },
  { immediate: true }
)
</script>

<template>
  <section class="chat-panel" data-testid="chat-panel">
    <div class="chat-body">
      <ChatHistorySidebar
        ref="historySidebar"
        :kb-id="props.kbId"
        :active-session-id="sessionId"
        @select="handleSelectSession"
        @create="handleCreateFromSidebar"
        @deleted="handleSessionDeleted"
      />
      <div class="chat-main">
        <header class="panel-header">
          <div><h2>技术文档问答</h2><p>回答仅基于已完成索引的当前知识库文档。</p></div>
          <el-button v-if="sending" type="danger" plain :icon="CircleClose" @click="cancel">取消生成</el-button>
        </header>
        <div ref="transcript" class="transcript" aria-live="polite">
          <el-empty v-if="messages.length === 0" description="输入类名、错误码、配置项或技术问题开始检索" />
          <article v-for="message in messages" :key="message.id" class="message" :class="`message-${message.role}`">
            <span class="message-label">{{ message.role === 'user' ? '你' : message.role === 'refusal' ? '检索结果' : '知识库助手' }}</span>
            <div
              v-if="message.role === 'assistant' && message.content"
              class="message-content message-content-markdown"
              v-html="renderMarkdown(message.content)"
              @click="(event: MouseEvent) => handleCitationClick(event, message)"
            />
            <p v-else class="message-content">{{ message.content || (sending ? '正在生成…' : '') }}</p>
            <p v-if="message.selfCheckWarning" class="self-check-warning">{{ message.selfCheckWarning }}</p>
          </article>
        </div>
        <form class="composer" @submit.prevent="ask">
          <el-input
            v-model="question"
            type="textarea"
            :rows="3"
            maxlength="2000"
            show-word-limit
            :disabled="sending"
            placeholder="例如：SearchService 启动失败如何排查？（Enter 发送，Shift+Enter 换行）"
            @keydown="handleComposerKeydown"
          />
          <el-button type="primary" native-type="submit" :icon="Promotion" :loading="sending" :disabled="!canSend">发送</el-button>
        </form>
      </div>
    </div>
    <el-drawer
      v-model="citationDrawerVisible"
      title="引用来源"
      direction="rtl"
      size="380px"
      data-testid="citation-drawer"
    >
      <div v-if="selectedCitation" class="citation-detail">
        <strong>[{{ selectedCitationIndex }}] {{ selectedCitation.documentName || '文档不可访问' }}</strong>
        <span v-if="citationLocation(selectedCitation)" class="citation-location">{{ citationLocation(selectedCitation) }}</span>
        <p class="citation-snippet">{{ selectedCitation.snippet }}</p>
        <small v-if="selectedCitation.score !== null">相关度 {{ selectedCitation.score.toFixed(3) }}</small>
      </div>
    </el-drawer>
  </section>
</template>

<style scoped>
.chat-panel { display: flex; min-height: 0; flex: 1; flex-direction: column; }
.chat-body { display: flex; min-height: 0; flex: 1; }
.chat-main { display: flex; min-height: 0; flex: 1; flex-direction: column; gap: 14px; padding-left: 14px; }
.panel-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.panel-header h2 { margin: 0; font-size: 18px; }
.panel-header p { margin: 5px 0 0; color: var(--el-text-color-secondary); font-size: 13px; }
.transcript { min-height: 280px; flex: 1; overflow: auto; border: 1px solid var(--brand-border); border-radius: 8px; padding: 14px; background: var(--brand-surface-soft); }
.message { max-width: 92%; margin: 0 0 14px; border-radius: 8px; padding: 10px 12px; background: var(--brand-surface); border: 1px solid var(--brand-border-soft); }
.message-user { margin-left: auto; background: var(--el-color-primary-light-9); }
.message-refusal { border-color: var(--el-color-warning-light-5); background: var(--el-color-warning-light-9); }
.message-error { border-color: var(--el-color-danger-light-5); background: var(--el-color-danger-light-9); }
.message-label { color: var(--el-text-color-secondary); font-size: 12px; }
.message-content { margin: 5px 0 0; line-height: 1.6; }
.message-content:not(.message-content-markdown) { white-space: pre-wrap; }
/* v-html 注入的内容不受 scoped 属性选择器约束，需要 :deep() 才能命中。
   marked 已经用 <p>/<ul>/<pre> 等块级元素处理换行，这里不需要再叠加 pre-wrap。 */
.message-content-markdown :deep(p) { margin: 0 0 8px; }
.message-content-markdown :deep(p:last-child) { margin-bottom: 0; }
.message-content-markdown :deep(ul),
.message-content-markdown :deep(ol) { margin: 0 0 8px; padding-left: 1.4em; }
.message-content-markdown :deep(li) { margin: 2px 0; }
.message-content-markdown :deep(strong) { font-weight: 600; }
.message-content-markdown :deep(code) {
  background: var(--el-fill-color-light);
  border-radius: 3px;
  padding: 1px 5px;
  font-size: 0.9em;
}
.message-content-markdown :deep(pre) {
  background: var(--el-fill-color-light);
  border-radius: 6px;
  padding: 10px 12px;
  overflow-x: auto;
  margin: 0 0 8px;
}
.message-content-markdown :deep(pre code) { background: none; padding: 0; }
.message-content-markdown :deep(blockquote) {
  margin: 0 0 8px;
  padding-left: 10px;
  border-left: 3px solid var(--brand-border);
  color: var(--el-text-color-secondary);
}
.message-content-markdown :deep(h1),
.message-content-markdown :deep(h2),
.message-content-markdown :deep(h3) { margin: 10px 0 6px; font-size: 1.05em; }
.message-content-markdown :deep(a) { color: var(--el-color-primary); }
.message-content-markdown :deep(.citation-ref) {
  color: var(--el-color-primary);
  cursor: pointer;
  font-weight: 600;
  padding: 0 1px;
}
.message-content-markdown :deep(.citation-ref:hover) { text-decoration: underline; }
.citation-detail { display: flex; flex-direction: column; gap: 8px; font-size: 13px; }
.citation-location, .citation-detail small { color: var(--el-text-color-secondary); }
.citation-snippet {
  margin: 0;
  padding: 10px;
  border-radius: 6px;
  border-left: 3px solid var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
  white-space: pre-wrap;
  line-height: 1.6;
}
.self-check-warning {
  margin: 10px 0 0;
  padding: 8px 10px;
  border-radius: 5px;
  border: 1px solid var(--el-color-warning-light-5);
  background: var(--el-color-warning-light-9);
  color: var(--el-text-color-primary);
  font-size: 13px;
  white-space: pre-wrap;
}
.composer { display: flex; align-items: flex-end; gap: 10px; }
.composer .el-textarea { flex: 1; }
@media (max-width: 760px) { .composer { flex-direction: column; align-items: stretch; } .message { max-width: 100%; } }
</style>
