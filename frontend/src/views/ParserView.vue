<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, ref } from 'vue'

import { api, type ParserFile } from '@/api/bridge'
import { useTaskPolling } from '@/composables/useTaskPolling'
import LogConsole from '@/components/LogConsole.vue'
import PageHeader from '@/components/PageHeader.vue'
import { progressPercent } from '@/utils/progress'

const outputDir = ref('')
const format = ref('unicloud')
const files = ref<ParserFile[]>([])
const picking = ref(false)
const starting = ref(false)
const { state, logs, active, reset, refresh } = useTaskPolling(api.parserState)

const validFiles = computed(() => files.value.filter((item) => item.valid))
const totalSize = computed(() =>
  files.value.reduce((total, item) => total + item.size, 0),
)
const progress = computed(() => progressPercent(state.value.current, state.value.total))
const statusText = computed(() => {
  const map: Record<string, string> = {
    idle: '空闲',
    starting: '准备解析',
    running: '解析中',
    aborting: '正在中止',
    aborted: '已中止',
    finished: '已完成',
    error: '执行失败',
  }
  return map[state.value.status] ?? state.value.status
})

function formatSize(size: number) {
  if (size >= 1024 * 1024) {
    return `${(size / 1024 / 1024).toFixed(1)} MB`
  }
  return `${Math.max(1, Math.round(size / 1024))} KB`
}

async function pick() {
  picking.value = true
  try {
    const paths = await api.parserPickFiles()
    if (paths.length > 0) {
      files.value = await api.parserInspectFiles(paths)
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : String(error))
  } finally {
    picking.value = false
  }
}

async function pickOutput() {
  const dir = await api.shellPickDirectory()
  if (dir) {
    outputDir.value = dir
  }
}

async function start() {
  if (validFiles.value.length === 0) {
    ElMessage.warning('请先选择通过校验的字幕文件')
    return
  }
  const invalidCount = files.value.length - validFiles.value.length
  if (invalidCount > 0) {
    try {
      await ElMessageBox.confirm(`有 ${invalidCount} 个文件未通过校验，将跳过。`, '确认解析', {
        confirmButtonText: '继续解析',
        cancelButtonText: '返回修改',
        type: 'warning',
      })
    } catch {
      return
    }
  }
  starting.value = true
  try {
    await api.parserStart({
      files: validFiles.value.map((item) => item.path),
      outputDir: outputDir.value,
      format: format.value,
    })
    reset()
    await refresh()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : String(error))
  } finally {
    starting.value = false
  }
}

async function abort() {
  await api.parserAbort()
  ElMessage.info('已请求中止解析')
}

</script>

<template>
  <div>
    <PageHeader title="字幕解析" subtitle="导入本地 SRT / ASS，生成电影、字幕与搜索索引导入文件">
      <el-button :disabled="active" @click="pick">选择文件</el-button>
      <el-button v-if="active" type="danger" plain @click="abort">中止解析</el-button>
    </PageHeader>

    <div class="app-cols">
      <div class="app-card">
        <div class="card-title">导入文件<span class="sub">有效 {{ validFiles.length }} 个</span></div>
        <div class="drop" @click="pick">
          <div class="big">⇩</div>
          <b>点击选择字幕文件</b>
          <div class="hint">支持 .srt / .ass，文件需大于 100KB 且包含简体中文和英文</div>
        </div>

        <div v-if="files.length" class="file-list">
          <div v-for="item in files" :key="item.path" class="file-row">
            <div class="file-main">
              <div class="file-name">{{ item.name }}</div>
              <div class="file-meta">{{ formatSize(item.size) }} · {{ item.valid ? '校验通过' : item.reason }}</div>
            </div>
            <span class="app-tag" :class="item.valid ? 'ok' : 'fail'">{{ item.valid ? '可解析' : '跳过' }}</span>
            <el-button link size="small" @click="files = files.filter((file) => file.path !== item.path)">移除</el-button>
          </div>
          <div class="summary">合计 {{ files.length }} 个文件 · {{ formatSize(totalSize) }}</div>
        </div>

        <div class="field">
          <label>导出格式</label>
          <el-radio-group v-model="format">
            <el-radio-button value="unicloud">uniCloud 导入</el-radio-button>
            <el-radio-button value="standard">标准 JSON</el-radio-button>
          </el-radio-group>
        </div>
        <div class="field">
          <label>输出目录</label>
          <div class="path-row">
            <el-input v-model="outputDir" placeholder="留空使用数据目录\\parsed" />
            <el-button @click="pickOutput">选择</el-button>
          </div>
        </div>
        <el-button type="primary" style="width: 100%" :loading="starting || active" @click="start">
          开始解析
        </el-button>
      </div>

      <div class="app-col">
        <div class="app-card">
          <div class="card-title">解析进度<span class="sub">{{ statusText }}</span></div>
          <el-progress
            :percentage="progress"
            :show-text="false"
            :stroke-width="8"
          />
          <div class="progress-meta">
            <span class="muted">{{ state.currentItem || '等待开始' }}</span>
            <b>{{ state.current }} / {{ state.total || '—' }}</b>
          </div>
          <div class="app-grid g3" style="margin-top: 14px">
            <div><div class="muted">成功</div><b style="color: var(--app-green)">{{ state.stats.successCount ?? 0 }}</b></div>
            <div><div class="muted">失败</div><b style="color: var(--app-red)">{{ state.stats.failureCount ?? 0 }}</b></div>
            <div><div class="muted">导出字幕</div><b>{{ state.stats.exportCount ?? 0 }}</b></div>
          </div>
          <div v-if="state.error" class="error">{{ state.error }}</div>
          <div v-if="state.outputPaths.length" class="outputs">
            <div v-for="path in state.outputPaths" :key="path" class="output-row">
              <span class="mono" :title="path">{{ path }}</span>
              <el-button link size="small" @click="api.shellOpenPath(path)">打开</el-button>
            </div>
          </div>
        </div>

        <div class="app-card">
          <div class="card-title">解析日志<span class="sub">自动滚动</span></div>
          <LogConsole :lines="logs" fill />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.drop {
  padding: 32px 20px;
  border: 1.5px dashed #cbd5e1;
  border-radius: 12px;
  background: #fbfcfe;
  text-align: center;
  color: var(--app-text-2);
  margin-bottom: 12px;
  cursor: pointer;
  transition: border-color 120ms ease, background 120ms ease;
}

.drop:hover {
  border-color: var(--app-brand);
  background: var(--app-brand-soft);
}

.drop .big {
  font-size: 26px;
  margin-bottom: 6px;
}

.drop .hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--app-text-3);
}

.file-list {
  margin-bottom: 12px;
  max-height: 260px;
  overflow-y: auto;
}

.file-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px solid var(--app-line-soft);
}

.file-main {
  flex: 1;
  min-width: 0;
}

.file-name {
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-meta {
  font-size: 12px;
  color: var(--app-text-3);
}

.summary {
  padding-top: 8px;
  font-size: 12px;
  color: var(--app-text-3);
}

.path-row {
  display: flex;
  gap: 8px;
}

.progress-meta {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
}

.outputs {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--app-line-soft);
}
</style>
