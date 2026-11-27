<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, reactive, ref, watch } from 'vue'

import { api } from '@/api/bridge'
import { useTaskPolling } from '@/composables/useTaskPolling'
import LogConsole from '@/components/LogConsole.vue'
import PageHeader from '@/components/PageHeader.vue'
import { progressPercent } from '@/utils/progress'

const form = reactive({
  year: '2026',
  limit: '50',
  concurrency: '2',
  interval: '8000',
  ratio: '0.70',
})

const providers = reactive([
  { id: 'subhd', label: 'SubHD', enabled: true, configured: true },
  { id: 'assrt', label: 'ASSRT', enabled: true, configured: true },
  { id: 'opensubtitles', label: 'OpenSubtitles', enabled: true, configured: true },
  { id: 'subdl', label: 'SubDL', enabled: false, configured: false },
])

const { state, logs, active, reset, refresh } = useTaskPolling(api.collectorState)
const busy = ref(false)
const dragIndex = ref<number | null>(null)
const dragOverIndex = ref<number | null>(null)
const captchaOpen = ref(false)
const captchaCode = ref('')
const captchaError = ref('')

const running = computed(() => state.value.status === 'running')
const paused = computed(() => state.value.status === 'paused')
const progress = computed(() => progressPercent(state.value.current, state.value.total))
const statusText = computed(() => {
  const map: Record<string, string> = {
    idle: '空闲',
    starting: '准备启动',
    running: '采集中',
    pausing: '正在暂停',
    paused: '已暂停',
    aborting: '正在中止',
    aborted: '已中止',
    finished: '已完成',
    error: '执行失败',
  }
  return map[state.value.status] ?? state.value.status
})

const statNumber = (key: string) => Number(state.value.stats[key] ?? 0)

// 按当前排序实时计算优先级，拖动后立即同步“优先 N”
const priorityText = (item: (typeof providers)[number], index: number) => {
  if (!item.configured) {
    return '未配置'
  }
  return item.enabled ? `优先 ${index + 1}` : '已停用'
}

watch(
  () => state.value.verification,
  (verification) => {
    if (!verification) {
      captchaOpen.value = false
      return
    }
    captchaCode.value = verification.suggestedCode || ''
    captchaError.value = ''
    captchaOpen.value = true
  },
)

async function start() {
  if (!providers.some((item) => item.enabled)) {
    ElMessage.warning('请至少选择一个字幕源')
    return
  }
  busy.value = true
  try {
    await api.collectorStart({
      year: Number(form.year),
      limit: Number(form.limit),
      concurrency: Number(form.concurrency),
      requestIntervalMs: Number(form.interval),
      minBilingualRatio: Number(form.ratio),
      providers: providers.filter((item) => item.enabled).map((item) => item.id),
    })
    reset()
    await refresh()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : String(error))
  } finally {
    busy.value = false
  }
}

async function pause() {
  await api.collectorPause()
  await refresh()
}

async function resume() {
  await api.collectorResume()
  await refresh()
}

async function abort() {
  try {
    await ElMessageBox.confirm('中止后未完成的电影会跳过，已完成结果会保留。', '中止采集', {
      confirmButtonText: '中止任务',
      cancelButtonText: '继续采集',
      type: 'warning',
    })
    await api.collectorAbort()
    await refresh()
  } catch {
    // 用户取消
  }
}

async function submitCaptcha() {
  if (!captchaCode.value.trim()) {
    captchaError.value = '请输入验证码'
    return
  }
  try {
    await api.collectorSubmitVerification(captchaCode.value.trim())
    captchaOpen.value = false
  } catch (error) {
    captchaError.value = error instanceof Error ? error.message : String(error)
  }
}

async function refreshCaptcha() {
  try {
    await api.collectorRefreshCaptcha()
    ElMessage.info('已请求刷新验证码')
  } catch (error) {
    captchaError.value = error instanceof Error ? error.message : String(error)
  }
}

function onDragStart(index: number) {
  dragIndex.value = index
}

function onDragOver(index: number) {
  if (dragIndex.value !== null && dragIndex.value !== index) {
    dragOverIndex.value = index
  }
}

function onDragEnd() {
  dragIndex.value = null
  dragOverIndex.value = null
}

function onDrop(index: number) {
  if (dragIndex.value === null || dragIndex.value === index) {
    onDragEnd()
    return
  }
  const [item] = providers.splice(dragIndex.value, 1)
  providers.splice(index, 0, item)
  onDragEnd()
}
</script>

<template>
  <div>
    <PageHeader title="开始采集" subtitle="按 TMDb 榜单拉取电影，逐部搜索并下载最匹配的双语字幕" />

    <div class="app-cols">
      <div class="app-card">
        <div class="card-title">采集参数<span class="sub">拖动字幕源调整优先级</span></div>
        <div class="row">
          <div class="field">
            <label>年份</label>
            <el-input v-model="form.year" type="number" />
          </div>
          <div class="field">
            <label>采集数量</label>
            <el-input v-model="form.limit" type="number" />
          </div>
        </div>

        <div class="field">
          <label>字幕源优先级</label>
          <div
            v-for="(item, index) in providers"
            :key="item.id"
            class="check-row"
            :class="{
              dragging: dragIndex === index,
              'drop-target': dragOverIndex === index,
            }"
            draggable="true"
            @dragstart="onDragStart(index)"
            @dragend="onDragEnd"
            @dragover.prevent="onDragOver(index)"
            @dragleave="dragOverIndex = null"
            @drop="onDrop(index)"
          >
            <span class="drag-handle" title="拖动调整优先级" aria-hidden="true">
              <svg viewBox="0 0 16 24">
                <circle cx="5.5" cy="5" r="1.8" />
                <circle cx="10.5" cy="5" r="1.8" />
                <circle cx="5.5" cy="12" r="1.8" />
                <circle cx="10.5" cy="12" r="1.8" />
                <circle cx="5.5" cy="19" r="1.8" />
                <circle cx="10.5" cy="19" r="1.8" />
              </svg>
            </span>
            <el-checkbox v-model="item.enabled">{{ item.label }}</el-checkbox>
            <span class="meta">{{ priorityText(item, index) }}</span>
          </div>
        </div>

        <div class="row">
          <div class="field">
            <label>电影并发</label>
            <el-input v-model="form.concurrency" type="number" />
          </div>
          <div class="field">
            <label>请求间隔 ms</label>
            <el-input v-model="form.interval" type="number" />
          </div>
        </div>

        <div class="field">
          <label>最低双语比例</label>
          <el-input v-model="form.ratio" type="number" step="0.05" />
        </div>

        <el-button v-if="!running && !paused" type="primary" style="width: 100%" :loading="busy || active" @click="start">
          开始采集
        </el-button>
        <div v-else class="row">
          <el-button v-if="running" @click="pause">暂停</el-button>
          <el-button v-else @click="resume">继续</el-button>
          <el-button type="danger" plain @click="abort">中止</el-button>
        </div>

        <div v-if="state.error" class="error">{{ state.error }}</div>
      </div>

      <div class="app-col">
        <div class="app-card">
          <div class="card-title">
            运行状态
            <span class="sub">{{ state.currentItem || '尚未开始' }}</span>
          </div>
          <el-progress :percentage="progress" :show-text="false" :stroke-width="8" />
          <div class="progress-meta">
            <span class="muted">{{ progress }}%</span>
            <b>{{ state.current }} / {{ state.total || '—' }}</b>
          </div>
          <div class="divider" />
          <div class="app-grid g4">
            <div><div class="muted">已下载</div><b>{{ statNumber('downloadCount') }}</b></div>
            <div><div class="muted">失败</div><b style="color: var(--app-red)">{{ statNumber('failedCount') }}</b></div>
            <div><div class="muted">电影</div><b>{{ statNumber('movieCount') }}</b></div>
            <div>
              <div class="muted">状态</div>
              <b>{{ statusText }}</b>
            </div>
          </div>
          <div v-if="state.stats.downloadDir" class="output-line">
            <span class="mono">{{ state.stats.downloadDir }}</span>
            <el-button link size="small" @click="api.shellOpenPath(String(state.stats.downloadDir))">打开</el-button>
          </div>
        </div>

        <div class="app-card">
          <div class="card-title">实时日志<span class="sub">最近 2000 条 · 自动滚动</span></div>
          <LogConsole :lines="logs" fill />
        </div>
      </div>
    </div>

    <el-dialog v-model="captchaOpen" title="需要人工验证" width="420px" :close-on-click-modal="false">
      <div v-if="state.verification" class="captcha-body">
        <div class="muted">{{ state.verification.provider }} · {{ state.verification.subtitleTitle }}</div>
        <img
          v-if="state.verification.verificationImageDataUri"
          class="captcha-image"
          :src="state.verification.verificationImageDataUri"
          alt="验证码"
        />
        <div v-else class="captcha-placeholder">该字幕源要求在网页内完成验证，请查看下方详情链接。</div>
        <el-input v-model="captchaCode" maxlength="8" placeholder="输入验证码" @keyup.enter="submitCaptcha" />
        <div v-if="state.verification.suggestedCode" class="hint">
          OCR 建议：{{ state.verification.suggestedCode }}（置信度
          {{ Math.round(state.verification.suggestedConfidence * 100) }}%）
        </div>
        <div v-if="captchaError" class="error">{{ captchaError }}</div>
      </div>
      <template #footer>
        <el-button @click="refreshCaptcha">换一张</el-button>
        <el-button @click="captchaOpen = false">稍后处理</el-button>
        <el-button type="primary" @click="submitCaptcha">提交验证码</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  gap: 10px;
}

.row > * {
  flex: 1;
  min-width: 0;
}

.check-row {
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 44px;
  padding: 6px 12px;
  border: 1px solid var(--app-line);
  border-radius: 9px;
  margin-bottom: 8px;
  background: #fff;
  cursor: grab;
  transition:
    border-color 120ms ease,
    background 120ms ease;
}

.check-row:hover {
  border-color: #cbd5e1;
  background: #fbfdff;
}

.check-row.dragging {
  border-color: #bfdbfe;
  background: var(--app-brand-soft);
  opacity: 0.65;
}

.check-row.drop-target {
  border-color: var(--app-brand);
  box-shadow: inset 0 2px 0 var(--app-brand);
}

.check-row .meta {
  margin-left: auto;
  font-size: 12px;
  color: var(--app-text-3);
}

.drag-handle {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  flex: 0 0 32px;
  margin-left: -6px;
  border-radius: 6px;
  color: #8b98ab;
  cursor: grab;
}

.drag-handle:hover {
  background: #e8eef7;
  color: var(--app-text-2);
}

.drag-handle svg {
  width: 16px;
  height: 24px;
  fill: currentColor;
}

.progress-meta {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
}

.output-line {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--app-line-soft);
  font-size: 12px;
  color: var(--app-text-3);
  overflow: hidden;
}

.output-line .mono {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.captcha-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.captcha-image {
  max-height: 120px;
  object-fit: contain;
  border: 1px solid var(--app-line);
  border-radius: 8px;
  background: #fff;
}

.captcha-placeholder {
  padding: 18px;
  border: 1px dashed var(--app-line);
  border-radius: 8px;
  color: var(--app-text-3);
  font-size: 12px;
}

</style>
