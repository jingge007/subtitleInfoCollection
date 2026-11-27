<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '@/api/bridge'
import { useTaskPolling } from '@/composables/useTaskPolling'
import LogConsole from '@/components/LogConsole.vue'
import PageHeader from '@/components/PageHeader.vue'
import { progressPercent } from '@/utils/progress'

const router = useRouter()
const format = ref('unicloud')
const starting = ref('')
const { state, logs, active, reset, refresh } = useTaskPolling(api.automationState)

const progress = computed(() => progressPercent(state.value.current, state.value.total))

const statusText = computed(() => {
  const map: Record<string, string> = {
    idle: '空闲',
    starting: '准备启动',
    running: '运行中',
    finished: '执行完成',
    error: '执行失败',
    aborted: '已中止',
    aborting: '正在中止',
  }
  return map[state.value.status] ?? state.value.status
})

async function startToday() {
  starting.value = 'today'
  try {
    await api.automationStartTodays({ format: format.value })
    reset()
    await refresh()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : String(error))
  } finally {
    starting.value = ''
  }
}

async function abort() {
  try {
    await ElMessageBox.confirm('确定中止当前自动化任务吗？', '中止任务', {
      confirmButtonText: '中止',
      cancelButtonText: '继续运行',
      type: 'warning',
    })
    await api.automationAbort()
  } catch {
    // 用户取消
  }
}
</script>

<template>
  <div>
    <PageHeader title="自动化" subtitle="33 台词相关任务，与字幕采集主流程独立运行">
      <el-button v-if="active" type="danger" plain @click="abort">中止任务</el-button>
    </PageHeader>

    <div class="app-grid g2">
      <div class="app-card">
        <div class="card-title">今日台词<span class="sub">抓取当天台词并补齐英文</span></div>
        <div class="app-kv"><span class="k">登录账号</span><span class="v">读取配置项</span></div>
        <div class="app-kv"><span class="k">Token</span><span class="v">自动登录与缓存</span></div>
        <div class="app-kv"><span class="k">百度翻译</span><span class="v">配置后自动补齐</span></div>
        <div class="divider" />
        <div class="field">
          <label>输出格式</label>
          <el-radio-group v-model="format">
            <el-radio-button value="unicloud">uniCloud</el-radio-button>
            <el-radio-button value="standard">标准 JSON</el-radio-button>
          </el-radio-group>
        </div>
        <el-button type="primary" style="width: 100%" :loading="starting === 'today' || active" @click="startToday">
          开始运行
        </el-button>
      </div>

      <div class="app-card">
        <div class="card-title">经典台词<span class="sub">全量采集与字段校验</span></div>
        <div class="app-kv"><span class="k">并发</span><span class="v">8（可在运行页调整）</span></div>
        <div class="app-kv"><span class="k">页数上限</span><span class="v">默认不限</span></div>
        <div class="app-kv"><span class="k">输出</span><span class="v">电影 + 台词 + 详情</span></div>
        <div class="divider" />
        <div class="field">
          <label>运行方式</label>
          <div class="hint">经典台词任务较长，建议进入独立运行页查看实时进度与产物。</div>
        </div>
        <el-button style="width: 100%" @click="router.push('/classic')">
          进入运行页
        </el-button>
      </div>
    </div>

    <div class="app-grid g2 workspace-grid">
      <div class="app-card">
        <div class="card-title">运行进度<span class="sub">{{ state.currentItem || statusText }}</span></div>
        <el-progress :percentage="progress" :show-text="false" :stroke-width="8" />
        <div class="app-grid g4 metrics">
          <div><div class="muted">进度</div><b>{{ state.current }} / {{ state.total || '—' }}</b></div>
          <div><div class="muted">已导出</div><b>{{ state.stats.totalCount ?? state.stats.totalLines ?? 0 }}</b></div>
          <div><div class="muted">跳过</div><b>{{ state.stats.skippedCount ?? state.stats.failedMovies ?? 0 }}</b></div>
          <div><div class="muted">状态</div><b>{{ statusText }}</b></div>
        </div>
        <div v-if="state.outputPaths.length" class="outputs">
          <div v-for="path in state.outputPaths" :key="path" class="output-row">
            <span class="mono" :title="path">{{ path }}</span>
            <el-button link size="small" @click="api.shellOpenPath(path)">打开</el-button>
          </div>
        </div>
        <div v-if="state.error" class="error">{{ state.error }}</div>
      </div>

      <div class="app-card">
        <div class="card-title">运行日志<span class="sub">最近 2000 条</span></div>
        <LogConsole :lines="logs" fill />
      </div>
    </div>
  </div>
</template>

<style scoped>
.hint {
  font-size: 12px;
  color: var(--app-text-3);
  line-height: 1.6;
}

.workspace-grid {
  margin-top: 16px;
}

.workspace-grid > .app-card + .app-card {
  margin-top: 0;
}

.metrics {
  gap: 12px;
  margin-top: 16px;
}

.metrics b {
  font-variant-numeric: tabular-nums;
}

.outputs {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--app-line-soft);
}
</style>
