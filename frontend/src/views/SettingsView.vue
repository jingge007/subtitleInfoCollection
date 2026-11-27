<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { api } from '@/api/bridge'
import PageHeader from '@/components/PageHeader.vue'
import { useAppStore } from '@/stores/app'

const app = useAppStore()
const downloading = ref(false)
const actionError = ref('')
let pollTimer = 0

const currentVersion = computed(() => app.info?.version ?? '0.2.2')
const update = computed(() => app.update)

const statusText = computed(() => {
  const map: Record<string, string> = {
    idle: '尚未检查',
    checking: '正在检查',
    latest: '已是最新',
    available: '发现新版本',
    downloading: '正在下载',
    ready: '等待重启安装',
    restarting: '正在重启',
    error: '检查或更新失败',
  }
  return update.value ? (map[update.value.status] ?? update.value.status) : '尚未检查'
})

onMounted(async () => {
  await app.loadInfo().catch(() => undefined)
  // 仅在尚未检查过时自动检查，避免每次进入设置页都消耗 GitHub API 配额
  if (!app.update || app.update.status === 'idle') {
    await app.checkUpdate(true).catch(() => undefined)
  }
})

onBeforeUnmount(() => {
  window.clearInterval(pollTimer)
})

async function checkUpdate() {
  actionError.value = ''
  try {
    await app.checkUpdate()
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  }
}

async function download() {
  downloading.value = true
  actionError.value = ''
  pollTimer = window.setInterval(() => {
    void app.refreshUpdateState().catch(() => undefined)
  }, 500)
  try {
    await api.downloadUpdate()
    await app.refreshUpdateState()
    ElMessage.success('更新包已下载，可重启安装')
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  } finally {
    window.clearInterval(pollTimer)
    downloading.value = false
  }
}

async function restart() {
  try {
    await ElMessageBox.confirm('应用将关闭并安装新版本，是否继续？', '重启并安装', {
      confirmButtonText: '立即重启',
      cancelButtonText: '稍后',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await api.applyUpdate()
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  }
}

async function resetHistory() {
  try {
    await ElMessageBox.confirm('将清空采集历史记录，但保留 output 文件，是否继续？', '重置历史', {
      confirmButtonText: '重置',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await api.historyReset()
    ElMessage.success('历史已重置')
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  }
}

async function deleteOutputs() {
  try {
    await ElMessageBox.confirm(
      '将删除 output 目录并清空历史，此操作不可撤销，是否继续？',
      '删除输出文件',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'error',
      },
    )
  } catch {
    return
  }
  try {
    await api.shellDeleteOutputs()
    ElMessage.success('输出文件和历史记录已清理')
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  }
}
</script>

<template>
  <div>
    <PageHeader title="设置与维护" subtitle="版本更新、本地数据维护与运行路径" />

    <div class="app-card update-card">
      <div class="card-title">
        关于与更新
        <span class="sub">Velopack Portable · 更新源 GitHub Releases</span>
      </div>

      <div class="version-row">
        <div class="version-badge">v{{ currentVersion }}</div>
        <div class="version-main">
          <div class="version-title">
            {{ update?.available ? `发现 v${update.latestVersion}` : `当前 v${currentVersion}` }}
            <span class="app-tag" :class="update?.available ? 'info' : update?.status === 'error' ? 'fail' : 'ok'">
              {{ statusText }}
            </span>
          </div>
          <div class="muted">
            {{ update?.available ? '下载完成后需重启应用替换程序目录' : '发布说明会显示在下方' }}
          </div>
        </div>
        <div class="version-actions">
          <el-button v-if="update?.available && update.status === 'available'" type="primary" @click="download">
            立即更新
          </el-button>
          <el-button v-else-if="downloading || update?.status === 'downloading'" type="primary" loading>
            下载中 {{ update?.progress ?? 0 }}%
          </el-button>
          <el-button v-else-if="update?.status === 'ready'" type="primary" @click="restart">
            重启并安装
          </el-button>
          <el-button v-else :loading="app.checking" @click="checkUpdate">检查更新</el-button>
        </div>
      </div>

      <el-progress
        v-if="update?.status === 'downloading' || update?.status === 'ready'"
        :percentage="update?.progress ?? 0"
        :stroke-width="6"
        style="margin-top: 12px"
      />
      <div v-if="update?.notes" class="release-notes">
        <div v-for="(line, index) in update.notes.split('\n')" :key="index">· {{ line }}</div>
      </div>
      <div v-if="update?.error || actionError" class="error">{{ update?.error || actionError }}</div>
    </div>

    <div class="app-grid g2" style="margin-top: 12px">
      <div class="app-card">
        <div class="card-title">数据维护</div>
        <div class="list-row">
          <div class="grow">
            <div class="name">重置历史</div>
            <div class="path">清空采集记录，保留 output 文件</div>
          </div>
          <el-button size="small" @click="resetHistory">重置</el-button>
        </div>
        <div class="list-row">
          <div class="grow">
            <div class="name danger">删除输出文件</div>
            <div class="path">删除 output 并清空历史</div>
          </div>
          <el-button size="small" type="danger" plain @click="deleteOutputs">删除</el-button>
        </div>
      </div>

      <div class="app-card">
        <div class="card-title">运行路径</div>
        <div class="app-kv">
          <span class="k">配置文件</span>
          <span class="v mono" :title="app.info?.envPath">{{ app.info?.envPath ?? '加载中…' }}</span>
        </div>
        <div class="app-kv">
          <span class="k">数据目录</span>
          <span class="v mono" :title="app.info?.dataDir">{{ app.info?.dataDir ?? '加载中…' }}</span>
        </div>
        <div class="app-kv">
          <span class="k">程序目录</span>
          <span class="v mono" :title="app.info?.programDir">{{ app.info?.programDir ?? '加载中…' }}</span>
        </div>
        <div class="app-kv">
          <span class="k">运行模式</span>
          <span class="v">{{ app.info?.frozen ? '便携安装版' : '源码开发版' }}</span>
        </div>
        <div class="path-actions">
          <el-button size="small" @click="api.shellOpenPath(app.info?.dataDir ?? '')">打开数据目录</el-button>
          <el-button size="small" @click="api.shellOpenPath(app.info?.programDir ?? '')">打开程序目录</el-button>
        </div>
      </div>
    </div>

    <div class="app-card" style="margin-top: 12px">
      <div class="card-title">更新说明</div>
      <div class="tips">
        <div>· 安装包、Portable 包与 <code>releases.win.json</code> 都发布在公开 GitHub Releases，客户端匿名读取。</div>
        <div>· <code>.env</code>、SQLite 数据、输出文件与 WebView2 缓存均位于用户目录，更新只替换程序目录。</div>
        <div>· 开发模式不会实际安装更新；请使用打包后的 Portable 版本验证升级流程。</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.update-card {
  border-color: #d6e6ff;
  background: linear-gradient(180deg, #f7fbff, #fff);
}

.version-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.version-badge {
  width: 54px;
  height: 54px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  background: #fff;
  border: 1px solid #d6e6ff;
  color: var(--app-brand);
  font-size: 13px;
  font-weight: 700;
}

.version-main {
  flex: 1;
  min-width: 0;
}

.version-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 700;
}

.version-actions {
  flex: 0 0 auto;
}

.release-notes {
  margin: 12px 0 0;
  padding: 10px 12px;
  border: 1px solid var(--app-line-soft);
  border-radius: 8px;
  background: #f8fafc;
  font-size: 12px;
  color: var(--app-text-2);
}

.list-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 0;
  border-bottom: 1px solid var(--app-line-soft);
}

.list-row:last-child {
  border-bottom: 0;
}

.list-row .grow {
  flex: 1;
  min-width: 0;
}

.list-row .name {
  font-size: 13px;
  font-weight: 600;
}

.list-row .name.danger {
  color: var(--app-red);
}

.list-row .path {
  font-size: 12px;
  color: var(--app-text-3);
}

.path-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}

.tips {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--app-text-2);
}

</style>
