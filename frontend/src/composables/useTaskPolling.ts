import { onBeforeUnmount, onMounted, ref } from 'vue'

import type { TaskState } from '@/api/bridge'

const ACTIVE = new Set(['starting', 'running', 'pausing', 'paused', 'aborting'])

// 轮询后台任务并按游标增量累积日志
export function useTaskPolling(fetcher: (cursor: number) => Promise<TaskState>, intervalMs = 500) {
  const state = ref<TaskState>({
    status: 'idle',
    current: 0,
    total: 0,
    currentItem: '',
    stats: {},
    error: '',
    outputPaths: [],
    logs: [],
    nextLogCursor: 0,
    verification: null,
    startedAt: 0,
    finishedAt: 0,
  })
  const logs = ref<string[]>([])
  const cursor = ref(0)
  const loading = ref(false)
  const active = ref(false)
  let timer = 0
  let inFlight = false

  // 拉取最新状态并合并新增日志
  async function refresh() {
    if (inFlight) {
      return state.value
    }
    inFlight = true
    loading.value = true
    try {
      const next = await fetcher(cursor.value)
      if (next.logs.length > 0) {
        logs.value.push(...next.logs)
        if (logs.value.length > 2000) {
          logs.value = logs.value.slice(-2000)
        }
      }
      cursor.value = next.nextLogCursor || cursor.value
      state.value = { ...next, logs: [] }
      active.value = ACTIVE.has(next.status)
      return state.value
    } finally {
      inFlight = false
      loading.value = false
    }
  }

  // 新一轮任务开始时清空旧日志
  function reset() {
    logs.value = []
    cursor.value = 0
    active.value = true
  }

  // 强制从服务端重新读取全部状态
  function reload() {
    cursor.value = 0
    logs.value = []
    return refresh()
  }

  function startPolling() {
    if (timer) {
      return
    }
    timer = window.setInterval(() => {
      void refresh().catch(() => undefined)
    }, intervalMs)
  }

  function stopPolling() {
    window.clearInterval(timer)
    timer = 0
  }

  onMounted(() => {
    void refresh().catch(() => undefined)
    startPolling()
  })

  onBeforeUnmount(stopPolling)

  return {
    state,
    logs,
    cursor,
    loading,
    active,
    refresh,
    reload,
    reset,
    startPolling,
    stopPolling,
  }
}
