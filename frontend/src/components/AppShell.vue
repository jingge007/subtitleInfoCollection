<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { api, type AppStatus } from '@/api/bridge'
import { useAppStore } from '@/stores/app'

import SideBar from './SideBar.vue'

const app = useAppStore()
const version = computed(() => app.info?.version ?? '0.2.3')
const status = ref<AppStatus>({
  collector: 'idle',
  parser: 'idle',
  automation: 'idle',
  active: false,
})
let statusTimer = 0

// 顶栏展示真实运行状态，避免固定显示“空闲”造成误解
const runtimeText = computed(() => {
  const value = status.value
  if (value.collector === 'paused') {
    return '采集已暂停'
  }
  if (['starting', 'running', 'pausing', 'aborting'].includes(value.collector)) {
    return '采集进行中'
  }
  if (['starting', 'running', 'aborting'].includes(value.parser)) {
    return '字幕解析中'
  }
  if (['starting', 'running', 'aborting'].includes(value.automation)) {
    return '自动化运行中'
  }
  return '空闲'
})

function onResize() {
  app.applyResponsive(window.innerWidth)
}

function onKeydown(event: KeyboardEvent) {
  if (event.ctrlKey && event.key.toLowerCase() === 'b') {
    event.preventDefault()
    app.toggleSidebar()
  }
}

async function togglePin() {
  try {
    await app.toggleAlwaysOnTop()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : String(error))
  }
}

// 依次排队启动调用，避免并发 js_api 请求阻塞 WinForms UI 线程
async function bootstrap() {
  try {
    await app.loadInfo()
  } catch (error) {
    ElMessage.error(
      `应用信息加载失败：${error instanceof Error ? error.message : String(error)}`,
    )
    return
  }
  try {
    await app.applyAlwaysOnTop()
  } catch (error) {
    console.warn('恢复窗口置顶状态失败', error)
  }
  void app.checkUpdate(true).catch(() => undefined)
}

// 轮询任务概览，仅取状态，不拉取日志
async function refreshStatus() {
  try {
    status.value = await api.appStatus()
  } catch {
    // 轮询失败保持上一次状态，避免顶栏闪烁
  }
}

onMounted(() => {
  app.applyResponsive(window.innerWidth)
  window.addEventListener('resize', onResize)
  window.addEventListener('keydown', onKeydown)
  void bootstrap()
  void refreshStatus()
  statusTimer = window.setInterval(refreshStatus, 2500)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  window.removeEventListener('keydown', onKeydown)
  window.clearInterval(statusTimer)
})
</script>

<template>
  <div class="shell" :class="{ collapsed: app.collapsed }">
    <SideBar />

    <div class="main">
      <header class="topbar">
        <el-tooltip
          :content="app.collapsed ? '展开侧边栏 (Ctrl+B)' : '收起侧边栏 (Ctrl+B)'"
          placement="bottom"
          :show-after="120"
        >
          <button
            class="sidebar-toggle"
            type="button"
            :aria-label="app.collapsed ? '展开侧边栏' : '收起侧边栏'"
            @click="app.toggleSidebar()"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <rect x="3.5" y="4.5" width="17" height="15" rx="2.5" />
              <path d="M9 4.5v15" />
              <path :d="app.collapsed ? 'm12.5 9 3 3-3 3' : 'm15 9-3 3 3 3'" />
            </svg>
          </button>
        </el-tooltip>

        <div class="topbar-actions">
          <el-tooltip
            :content="app.alwaysOnTop ? '取消窗口置顶' : '窗口置顶'"
            placement="bottom"
            :show-after="120"
          >
            <button
              class="pin-btn"
              :class="{ active: app.alwaysOnTop }"
              type="button"
              :aria-pressed="app.alwaysOnTop"
              :aria-label="app.alwaysOnTop ? '取消窗口置顶' : '窗口置顶'"
              @click="togglePin"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M9 4h6l-1 6 4 3v2H6v-2l4-3-1-6Z" />
                <path d="M12 15v5" />
              </svg>
            </button>
          </el-tooltip>

          <button
            v-if="app.update?.available"
            class="app-pill update-pill"
            type="button"
            @click="$router.push('/settings')"
          >
            <span class="status-dot busy" />
            新版本 {{ app.update.latestVersion }}
          </button>
          <span v-else class="app-pill">
            <span class="status-dot" :class="{ busy: status.active }" />
            {{ runtimeText }}
          </span>
          <span class="app-pill mono">v{{ version }}</span>
          <el-button @click="$router.push('/settings')">检查更新</el-button>
          <el-button type="primary" @click="$router.push('/collect')">开始采集</el-button>
        </div>
      </header>

      <div class="content">
        <div class="content-inner">
          <router-view />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.shell {
  --sidebar-width: 232px;
  display: flex;
  height: 100%;
  overflow: hidden;
}

.shell.collapsed {
  --sidebar-width: 64px;
}

.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.topbar {
  height: var(--header-height);
  flex: 0 0 var(--header-height);
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 24px;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--app-line);
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.sidebar-toggle {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  flex: 0 0 32px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--app-text-3);
  cursor: pointer;
  transition:
    background 120ms ease,
    color 120ms ease,
    border-color 120ms ease;
}

.sidebar-toggle:hover {
  border-color: var(--app-line);
  background: #f1f5f9;
  color: var(--app-text);
}

.sidebar-toggle svg {
  width: 18px;
  height: 18px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.pin-btn {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--app-text-3);
  cursor: pointer;
  transition:
    background 120ms ease,
    color 120ms ease,
    border-color 120ms ease;
}

.pin-btn:hover {
  border-color: var(--app-line);
  background: #f1f5f9;
  color: var(--app-text);
}

.pin-btn.active {
  border-color: #bfdbfe;
  background: var(--app-brand-soft);
  color: var(--app-brand);
}

.pin-btn svg {
  width: 17px;
  height: 17px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.content {
  flex: 1;
  overflow: auto;
  padding: 24px;
}

.content-inner {
  max-width: 1280px;
  margin: 0 auto;
}
</style>
