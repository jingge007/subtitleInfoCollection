<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, ref } from 'vue'

import { api } from '@/api/bridge'
import { useTaskPolling } from '@/composables/useTaskPolling'
import LogConsole from '@/components/LogConsole.vue'
import PageHeader from '@/components/PageHeader.vue'
import { progressPercent } from '@/utils/progress'

const concurrency = ref('8')
const maxPages = ref('')
const format = ref('unicloud')
const starting = ref(false)
const { state, logs, active, reset, refresh } = useTaskPolling(api.automationState)

const progress = computed(() => progressPercent(state.value.current, state.value.total))
const statusText = computed(() => {
  const map: Record<string, string> = {
    idle: '等待开始',
    starting: '准备启动',
    running: '运行中',
    aborting: '正在中止',
    aborted: '已中止',
    finished: '已完成',
    error: '执行失败',
  }
  return map[state.value.status] ?? state.value.status
})

async function start() {
  starting.value = true
  try {
    await api.automationStartClassic({
      concurrency: Number(concurrency.value || 8),
      maxPages: maxPages.value,
      format: format.value,
    })
    reset()
    await refresh()
    ElMessage.success('经典台词任务已启动')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : String(error))
  } finally {
    starting.value = false
  }
}

async function abort() {
  try {
    await ElMessageBox.confirm('确定中止经典台词任务吗？已抓取的结果不会写入导出文件。', '中止任务', {
      confirmButtonText: '中止',
      cancelButtonText: '继续',
      type: 'warning',
    })
    await api.automationAbort()
    ElMessage.info('已请求中止任务')
  } catch {
    // 用户取消
  }
}
</script>

<template>
  <div class="classic-layout">
    <PageHeader title="经典台词" subtitle="全量抓取任务，实时展示电影、台词与失败明细">
    </PageHeader>

    <div class="app-card param-card">
      <div class="card-title">任务参数<span class="sub">全量抓取配置</span></div>
      <div class="param-grid">
        <div class="field">
          <label>并发数</label>
          <el-input v-model="concurrency" type="number" min="1" max="12" />
        </div>
        <div class="field">
          <label>页数上限</label>
          <el-input v-model="maxPages" placeholder="留空表示不限" />
        </div>
        <div class="field">
          <label>输出格式</label>
          <el-radio-group v-model="format">
            <el-radio-button value="unicloud">uniCloud</el-radio-button>
            <el-radio-button value="standard">标准 JSON</el-radio-button>
          </el-radio-group>
        </div>
        <div class="param-meta">
          <div class="app-kv"><span class="k">浏览器模式</span><span class="v">无头</span></div>
          <div class="app-kv"><span class="k">字段校验</span><span class="v">开启</span></div>
        </div>
        <div class="action-stack">
          <el-button type="primary" :loading="starting || active" @click="start">
            开始采集
          </el-button>
          <el-button v-if="active" type="danger" plain @click="abort">
            中止任务
          </el-button>
        </div>
      </div>
    </div>

    <div class="app-grid g2 status-grid">
      <div class="app-card">
        <div class="card-title">进度<span class="sub">{{ state.currentItem || statusText }}</span></div>
        <el-progress :percentage="progress" :show-text="false" :stroke-width="8" />
        <div class="progress-meta">
          <span class="muted">{{ progress }}%</span>
          <b>{{ state.current }} / {{ state.total || '—' }}</b>
        </div>
        <div class="app-grid g3" style="margin-top: 14px">
          <div><div class="muted">已采集电影</div><b>{{ state.stats.totalMovies ?? 0 }}</b></div>
          <div><div class="muted">台词总数</div><b>{{ state.stats.totalLines ?? 0 }}</b></div>
          <div><div class="muted">失败</div><b style="color: var(--app-red)">{{ state.stats.failedMovies ?? 0 }}</b></div>
        </div>
        <div v-if="state.error" class="error">{{ state.error }}</div>
      </div>

      <div class="app-card">
        <div class="card-title">输出文件<span class="sub">{{ state.outputPaths.length }} 个</span></div>
        <div v-if="state.outputPaths.length" class="outputs">
          <div v-for="path in state.outputPaths" :key="path" class="output-row">
            <span class="mono" :title="path">{{ path }}</span>
            <el-button link size="small" @click="api.shellOpenPath(path)">打开</el-button>
          </div>
        </div>
        <div v-else class="empty">运行完成后显示产物</div>
      </div>
    </div>

    <div class="app-card log-card">
      <div class="card-title">实时日志<span class="sub">按页汇总成功与失败</span></div>
      <LogConsole :lines="logs" stretch />
    </div>
  </div>
</template>

<style scoped>
/* 整页竖向流：参数置顶、进度与产物并排、日志铺满剩余高度 */
.classic-layout {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: calc(100vh - var(--header-height) - 48px);
}

.classic-layout :deep(.app-card + .app-card) {
  margin-top: 0;
}

.classic-layout :deep(.page-header) {
  margin-bottom: 0;
}

.param-grid {
  display: grid;
  gap: 16px 20px;
  align-items: start;
  grid-template-columns:
    minmax(120px, 0.8fr)
    minmax(140px, 1fr)
    minmax(190px, 1.1fr)
    minmax(150px, 0.9fr)
    auto;
}

.param-grid .field {
  margin-bottom: 0;
}

.param-meta {
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.action-stack {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 132px;
}

.action-stack :deep(.el-button) {
  width: 100%;
}

.action-stack :deep(.el-button + .el-button) {
  margin-left: 0;
}

.status-grid {
  align-items: stretch;
}

.status-grid > .app-card {
  display: flex;
  flex-direction: column;
}

.progress-meta {
  display: flex;
  justify-content: space-between;
  margin-top: 10px;
}

.outputs {
  max-height: 180px;
  overflow: auto;
}

/* 日志卡片吃掉页面剩余高度，内部日志体随容器伸缩 */
.log-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 200px;
}

@media (max-width: 1180px) {
  .param-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .action-stack {
    grid-column: 1 / -1;
    max-width: 220px;
  }
}

@media (max-width: 900px) {
  .status-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 760px) {
  .param-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .action-stack {
    grid-column: auto;
    max-width: none;
  }
}
</style>
