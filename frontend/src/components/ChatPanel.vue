<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { CircleClose, Promotion } from '@element-plus/icons-vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { useAuthStore } from '@/stores/authStore'
import { openStream, queryStreamUrl } from '@/api/queryApi'
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

/** LLM 回答含 Markdown 语法（**加粗**、列表、代码块等），此前直接文本插值导致
 * 语法符号原样显示。仅对话回答需要渲染；用户自己打的话按纯文本展示，避免用户
 * 输入里的 `*`/`#` 被意外解释成 Markdown。渲染结果必须过 DOMPurify 净化后才能
 * 用 v-html 注入，防止检索到的文档内容里混入的 HTML/脚本片段被当作真实标签执行。 */
function renderMarkdown(content: string): string {
  const html = marked.parse(content, { async: false, breaks: true }) as string
  return DOMPurify.sanitize(html)
}

const canSend = computed(() => !!props.kbId && !!question.value.trim() && !sending.value)

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
      body: { question: text }, headers: headers(), signal: controller.signal
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

watch(() => props.kbId, () => { messages.value = []; question.value = ''; cancel() })
</script>

<template>
  <section class="chat-panel" data-testid="chat-panel">
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
        />
        <p v-else class="message-content">{{ message.content || (sending ? '正在生成…' : '') }}</p>
        <div v-if="message.citations?.length" class="citations">
          <p class="citation-title">参考来源</p>
          <article v-for="(citation, index) in message.citations" :key="`${citation.documentId}-${index}`" class="citation-card">
            <strong>[{{ index + 1 }}] {{ citation.documentName || '文档不可访问' }}</strong>
            <span v-if="citationLocation(citation)" class="citation-location">{{ citationLocation(citation) }}</span>
            <p>{{ citation.snippet }}</p>
            <small v-if="citation.score !== null">相关度 {{ citation.score.toFixed(3) }}</small>
          </article>
        </div>
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
  </section>
</template>

<style scoped>
.chat-panel { display: flex; min-height: 0; flex: 1; flex-direction: column; gap: 14px; }
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
.citations { margin-top: 10px; border-top: 1px dashed var(--el-border-color); padding-top: 8px; }
.citation-title { margin: 0 0 7px; color: var(--el-text-color-secondary); font-size: 12px; }
.citation-card { margin: 6px 0; padding: 8px; border-radius: 5px; background: var(--brand-surface-soft); border: 1px solid var(--brand-border-soft); font-size: 13px; }
.citation-card strong, .citation-card span, .citation-card small { display: block; }
.citation-card p { margin: 5px 0; white-space: pre-wrap; }
.citation-location, .citation-card small { color: var(--el-text-color-secondary); }
.composer { display: flex; align-items: flex-end; gap: 10px; }
.composer .el-textarea { flex: 1; }
@media (max-width: 760px) { .composer { flex-direction: column; align-items: stretch; } .message { max-width: 100%; } }
</style>
