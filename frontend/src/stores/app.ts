import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api, type AppInfo, type UpdateState } from '@/api/bridge'

const SIDEBAR_KEY = 'ui.sidebarCollapsed'
const ALWAYS_ON_TOP_KEY = 'ui.alwaysOnTop'

export const useAppStore = defineStore('app', () => {
  const collapsed = ref(localStorage.getItem(SIDEBAR_KEY) === '1')
  const alwaysOnTop = ref(localStorage.getItem(ALWAYS_ON_TOP_KEY) === '1')
  const autoApplied = ref(false)
  const info = ref<AppInfo | null>(null)
  const update = ref<UpdateState | null>(null)
  const checking = ref(false)
  const downloading = ref(false)
  const updateError = ref('')

  // 持久化侧边栏状态，重启后保持
  function persistCollapsed() {
    localStorage.setItem(SIDEBAR_KEY, collapsed.value ? '1' : '0')
  }

  function toggleSidebar() {
    collapsed.value = !collapsed.value
    persistCollapsed()
  }

  // 首次进入窄窗口时自动收起，不覆盖用户手动选择
  function applyResponsive(width: number) {
    if (autoApplied.value) {
      return
    }
    if (width < 1100) {
      autoApplied.value = true
      collapsed.value = true
      persistCollapsed()
    }
  }

  async function loadInfo() {
    if (info.value) {
      return info.value
    }
    info.value = await api.appInfo()
    return info.value
  }

  async function checkUpdate(silent = false) {
    // 启动页与设置页可能同时触发检查，复用进行中的请求
    if (checking.value) {
      return update.value
    }
    checking.value = true
    updateError.value = ''
    try {
      update.value = await api.checkUpdate()
      return update.value
    } catch (error) {
      updateError.value = error instanceof Error ? error.message : String(error)
      if (!silent) {
        throw error
      }
      return null
    } finally {
      checking.value = false
    }
  }

  async function refreshUpdateState() {
    update.value = await api.updateState()
    return update.value
  }

  // 恢复窗口置顶状态
  async function applyAlwaysOnTop() {
    const applied = await api.setAlwaysOnTop(alwaysOnTop.value)
    alwaysOnTop.value = Boolean(applied)
    localStorage.setItem(ALWAYS_ON_TOP_KEY, alwaysOnTop.value ? '1' : '0')
    return alwaysOnTop.value
  }

  // 切换窗口置顶，失败时回滚界面状态
  async function toggleAlwaysOnTop() {
    const next = !alwaysOnTop.value
    alwaysOnTop.value = next
    try {
      const applied = await api.setAlwaysOnTop(next)
      alwaysOnTop.value = Boolean(applied)
      localStorage.setItem(ALWAYS_ON_TOP_KEY, alwaysOnTop.value ? '1' : '0')
      return alwaysOnTop.value
    } catch (error) {
      alwaysOnTop.value = !next
      throw error
    }
  }

  return {
    collapsed,
    alwaysOnTop,
    info,
    update,
    checking,
    downloading,
    updateError,
    toggleSidebar,
    applyResponsive,
    loadInfo,
    checkUpdate,
    refreshUpdateState,
    applyAlwaysOnTop,
    toggleAlwaysOnTop,
  }
})
