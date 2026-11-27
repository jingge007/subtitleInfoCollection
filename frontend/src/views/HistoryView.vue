<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { api, type HistoryItem } from '@/api/bridge'
import PageHeader from '@/components/PageHeader.vue'
import { formatDateTime, formatDuration } from '@/utils/datetime'

const route = useRoute()
const loading = ref(true)
const keyword = ref(typeof route.query.keyword === 'string' ? route.query.keyword : '')
const page = ref(1)
const pageSize = 20
const items = ref<HistoryItem[]>([])
const total = ref(0)
const drawer = ref(false)
const current = ref<HistoryItem | null>(null)

async function load() {
  loading.value = true
  try {
    const data = await api.historyList(page.value, pageSize, keyword.value)
    items.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

// 任务状态标签，未知状态统一按信息色展示
const STATUS_TAGS: Record<string, { cls: string; text: string }> = {
  success: { cls: 'ok', text: '成功' },
  completed: { cls: 'ok', text: '成功' },
  partial: { cls: 'fail', text: '部分失败' },
  running: { cls: 'run', text: '运行中' },
  failed: { cls: 'fail', text: '失败' },
  error: { cls: 'fail', text: '失败' },
}

function statusTag(status: string) {
  return STATUS_TAGS[status] ?? { cls: 'info', text: status || '未知' }
}

function successCount(item: HistoryItem) {
  return Math.max(0, item.downloadCount)
}

async function search() {
  page.value = 1
  await load()
}

function openDetail(item: HistoryItem) {
  current.value = item
  drawer.value = true
}

onMounted(load)
</script>

<template>
  <div>
    <PageHeader title="历史记录" subtitle="每次采集运行的统计与产物">
      <el-input
        v-model="keyword"
        placeholder="搜索年份 / 状态 / 日期"
        style="width: 220px"
        clearable
        @keyup.enter="search"
        @clear="search"
      />
      <el-button @click="search">搜索</el-button>
    </PageHeader>

    <div class="app-card" style="padding: 6px 12px 12px">
      <el-table
        :data="items"
        v-loading="loading"
        row-key="id"
        class="history-table"
        style="width: 100%"
      >
        <el-table-column label="时间" min-width="180">
          <template #default="{ row }">
            <span class="cell-time mono">{{ formatDateTime(row.startedAt) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="year" label="年份" min-width="72" align="right" />
        <el-table-column prop="limit" label="数量" min-width="72" align="right" />
        <el-table-column label="影片" min-width="72" align="right">
          <template #default="{ row }">
            <span :class="row.movieCount > 0 ? 'num-ok' : 'num-zero'">{{ row.movieCount }}</span>
          </template>
        </el-table-column>
        <el-table-column label="成功" min-width="72" align="right">
          <template #default="{ row }">
            <span :class="successCount(row) > 0 ? 'num-ok' : 'num-zero'">{{ successCount(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="失败" min-width="72" align="right">
          <template #default="{ row }">
            <span :class="row.failedCount > 0 ? 'num-fail' : 'num-zero'">{{ row.failedCount }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" min-width="96">
          <template #default="{ row }">
            <span class="app-tag" :class="statusTag(row.status).cls">{{ statusTag(row.status).text }}</span>
          </template>
        </el-table-column>
        <el-table-column label="耗时" min-width="110" align="right">
          <template #default="{ row }">
            <span class="muted">{{ formatDuration(row.startedAt, row.finishedAt) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" align="right" width="90">
          <template #default="{ row }">
            <el-button link size="small" @click="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-button size="small" :disabled="page <= 1" @click="page -= 1; load()">上一页</el-button>
        <span class="muted">第 {{ page }} 页 · 共 {{ total }} 条</span>
        <el-button size="small" :disabled="page * pageSize >= total" @click="page += 1; load()">下一页</el-button>
      </div>
    </div>

    <el-drawer v-model="drawer" title="运行详情" size="50%">
      <template v-if="current">
        <div class="app-kv">
          <span class="k">开始时间</span>
          <span class="v mono">{{ formatDateTime(current.startedAt) }}</span>
        </div>
        <div class="app-kv"><span class="k">年份</span><span class="v">{{ current.year }}</span></div>
        <div class="app-kv"><span class="k">数量</span><span class="v">{{ current.limit }}</span></div>
        <div class="app-kv"><span class="k">影片</span><span class="v">{{ current.movieCount }}</span></div>
        <div class="app-kv"><span class="k">成功</span><span class="v">{{ successCount(current) }}</span></div>
        <div class="app-kv"><span class="k">失败</span><span class="v">{{ current.failedCount }}</span></div>
        <div class="app-kv"><span class="k">状态</span><span class="v">{{ statusTag(current.status).text }}</span></div>
        <div class="app-kv">
          <span class="k">结束时间</span>
          <span class="v mono">{{ formatDateTime(current.finishedAt) }}</span>
        </div>
        <div class="app-kv">
          <span class="k">耗时</span>
          <span class="v">{{ formatDuration(current.startedAt, current.finishedAt) }}</span>
        </div>
        <div class="app-kv detail-path">
          <span class="k">输出目录</span>
          <span class="v mono">{{ current.downloadDir || '—' }}</span>
        </div>
        <el-button
          size="small"
          style="margin-top: 12px"
          :disabled="!current.downloadDir"
          @click="api.shellOpenPath(current.downloadDir)"
        >
          打开输出目录
        </el-button>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.history-table :deep(.el-table__cell) {
  padding: 10px 0;
}

/* 时间列保持单行，避免 ISO 串折行 */
.cell-time {
  white-space: nowrap;
  color: var(--app-text-2);
}

.num-ok {
  color: var(--app-green);
  font-weight: 600;
}

.num-fail {
  color: var(--app-red);
  font-weight: 600;
}

.num-zero {
  color: var(--app-text-3);
}

.pager {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 12px;
}

.detail-path {
  align-items: flex-start;
}

.detail-path .v {
  text-align: right;
  word-break: break-all;
}
</style>
