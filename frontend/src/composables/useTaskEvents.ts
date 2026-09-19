// 实时事件通道:优先用 WebSocket,连不上就换 SSE。
//
// 用法:App 挂载时调用一次 startLiveEvents(),事件会自动写进 tasks/exports 仓库;
// 各组件只管读仓库,不需要自己建连接。

import { ref, watch } from 'vue'
import { urls } from '@/api/client'
import type { ExportEvent, TaskEvent } from '@/api/types'
import { useExportsStore } from '@/stores/exports'
import { useTasksStore } from '@/stores/tasks'

type Mode = 'ws' | 'sse' | 'offline'

let ws: WebSocket | null = null
let mode: Mode = 'ws'
let failures = 0 // 连续失败的次数,越多重连间隔越长
let sseById = new Map<string, EventSource>()
let started = false
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let refreshTimer: ReturnType<typeof setTimeout> | null = null
let unwatchWanted: (() => void) | null = null

// 每个任务最近收到的事件编号。重开 SSE 时带上它,后端就知道从哪条补起,
// 关流/断线那一小段漏掉的事件一条不丢
const lastEventId = new Map<string, number>()

/** 当前连接方式(这个值一变,界面右下角的小圆点自己跟着变色) */
export const liveStatus = ref<Mode>('offline')

function setMode(m: Mode) {
  mode = m
  liveStatus.value = m
}

function dispatch(data: unknown) {
  const msg = data as TaskEvent & Partial<ExportEvent>
  if (typeof msg.id === 'number' && msg.task_id) {
    const prev = lastEventId.get(msg.task_id) ?? 0
    if (msg.id > prev) lastEventId.set(msg.task_id, msg.id)
  }
  const tasks = useTasksStore()
  const exports_ = useExportsStore()
  if (msg.type.startsWith('export_')) {
    exports_.applyEvent(msg as ExportEvent)
  } else if (msg.type.startsWith('task_')) {
    tasks.applyEvent(msg as TaskEvent)
  }
}

/** 算出当前该开着哪些任务的 SSE 流:还在跑的任务一条,
 * 有导出在跑的任务也一条(任务跑完后想收导出进度就得盯住它的频道)。 */
function wantedSSE(): Map<string, boolean> {
  const tasks = useTasksStore()
  const exports_ = useExportsStore()
  const want = new Map<string, boolean>()
  for (const id of tasks.activeIds) want.set(id, false)
  for (const id of exports_.pendingTaskIds) {
    // 值表示"要盯到导出全跑完":任务本身还活着的流不用,任务结束才需要
    if (!want.has(id)) want.set(id, true)
  }
  return want
}

function openSSE() {
  const want = wantedSSE()
  // 先关掉不用再听的流(增量调整,别把好好的连接全拆了重连)
  for (const [id, es] of sseById) {
    if (!want.has(id)) {
      es.close()
      sseById.delete(id)
    }
  }
  for (const [id, watchExports] of want) {
    if (sseById.has(id)) continue
    const params = new URLSearchParams({
      after_event_id: String(lastEventId.get(id) ?? 0),
    })
    if (watchExports) params.set('watch', 'exports')
    const es = new EventSource(`${urls.sse(id)}?${params}`)
    es.onopen = () => {
      failures = 0
      setMode('sse')
      refreshAfterGap() // 断档期间可能有漏掉的状态,拿接口补一枪
    }
    es.onmessage = (e) => {
      try {
        dispatch(JSON.parse(e.data))
      } catch {
        // 解析不了的消息直接忽略
      }
    }
    es.addEventListener('end', () => {
      // 流自己收摊了(任务完事/导出全完事):摘掉,顺便重算一遍
      // 还要不要为别的导出再开一条
      es.close()
      sseById.delete(id)
      openSSE()
    }, { once: true })
    es.onerror = () => {
      // 网络闪断。EventSource 会自己无限重连,但我们每次重连都要带上
      // 新的事件编号,所以自己管:关掉,稍后统一重开
      es.close()
      sseById.delete(id)
      failures = Math.min(failures + 1, 5)
      scheduleReconnect()
    }
    sseById.set(id, es)
  }
}

function closeSSE() {
  for (const es of sseById.values()) es.close()
  sseById = new Map()
}

function scheduleReconnect() {
  if (reconnectTimer) return
  // 重连间隔一次比一次长,从 1 秒翻倍涨到最多 15 秒,免得疯狂重试
  const delay = Math.min(15000, 1000 * 2 ** Math.min(failures, 4))
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    if (mode === 'ws') connectWS()
    else if (mode === 'sse') openSSE()
  }, delay)
}

function connectWS() {
  try {
    ws = new WebSocket(urls.ws())
  } catch {
    failures++
    switchToSSEIfNeeded()
    scheduleReconnect()
    return
  }
  ws.onopen = () => {
    failures = 0
    setMode('ws')
    refreshAfterGap()
  }
  ws.onmessage = (e) => {
    try {
      dispatch(JSON.parse(e.data))
    } catch {
      // 忽略无法解析的消息
    }
  }
  ws.onclose = () => {
    ws = null
    failures++
    switchToSSEIfNeeded()
    // 不管接下来是重试 WS 还是走 SSE,都得等真连上才算"在线",
    // 中间这段先如实显示离线,别拿着还没建立的连接充数
    liveStatus.value = 'offline'
    scheduleReconnect()
  }
  ws.onerror = () => {
    // onclose 随后会触发,统一在那里处理
  }
}

function switchToSSEIfNeeded() {
  if (failures >= 3 && mode === 'ws') {
    // WS 连续失败(常见于代理不支持),退回 SSE 模式
    mode = 'sse'
  }
}

/** 断线重连后,把"错过的结果"用普通接口补一遍:
 * 还在跑的任务刷新一下最新状态,跑完才发现的导出拉一下列表。
 * 不补的话,恰好在断线时完成的任务会永远卡在界面上的"运行中"。
 * 一次重连可能同时开好几条流,每条都调一遍的话请求会翻倍,
 * 攒 200 毫秒合并成一次。 */
function refreshAfterGap() {
  if (refreshTimer) return
  refreshTimer = setTimeout(() => {
    refreshTimer = null
    const tasks = useTasksStore()
    const exports_ = useExportsStore()
    void Promise.allSettled([
      tasks.refreshActive(),
      ...[...exports_.pendingTaskIds].map((id) => exports_.load(id)),
    ])
  }, 200)
}

/** 应用启动时调一次,把全局的实时连接连上 */
export function startLiveEvents() {
  if (started) return
  started = true
  // 盯着"哪些任务需要开流":一旦变化(比如进任务列表页拉到了在跑的任务、
  // 发起了新导出),SSE 模式下自动把流开起来。不盯着的话,页面加载顺序
  // 稍有不巧,在跑的任务就一直没人给它开流,进度永远不动
  unwatchWanted = watch(wantedSSE, () => {
    if (started && mode === 'sse') openSSE()
  })
  connectWS()
}

/** 停止连接(一般只有 HMR/测试会用到) */
export function stopLiveEvents() {
  started = false
  if (reconnectTimer) clearTimeout(reconnectTimer)
  reconnectTimer = null
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshTimer = null
  unwatchWanted?.()
  unwatchWanted = null
  if (ws) {
    ws.onclose = null
    ws.close()
    ws = null
  }
  closeSSE()
}

/** 新建任务/发起导出后调用:SSE 模式下要补开对应的事件流(WS 是全量广播,不用管) */
export function ensureSubscribed() {
  if (started && mode === 'sse') openSSE()
}

// 开发热更时把旧连接收拾干净,不然模块被替换一次就多一条漏不掉的旧连接
if (import.meta.hot) {
  import.meta.hot.dispose(() => stopLiveEvents())
}

export { dispatch as dispatchLiveEvent }
