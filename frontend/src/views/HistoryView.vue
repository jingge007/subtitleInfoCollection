<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { api, type HistoryItem } from '@/api/bridge'
import PageHeader from '@/components/PageHeader.vue'

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

function statusTag(status: string) {
  if (status === 'success' || status === 'completed') {
    return { cls: 'ok', text: '成功' }
  }
  if (status === 'partial') {
    return { cls: 'fail', text: '部分失败' }
  }
  return { cls: 'run', text: status }
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
      <el-table :data="items" v-loading="loading" row-key="id" style="width: 100%">
        <el-table-column prop="startedAt" label="时间" width="150" />
        <el-table-column prop="year" label="年份" width="80" />
        <el-table-column prop="limit" label="数量" width="80" />
        <el-table-column label="成功" width="80">
          <template #default="{ row }">{{ successCount(row) }}</template>
        </el-table-column>
        <el-table-column prop="failedCount" label="失败" width="80" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <span class="app-tag" :class="statusTag(row.status).cls">{{ statusTag(row.status).text }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" align="right">
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

    <el-drawer v-model="drawer" title="运行详情" size="380px">
      <template v-if="current">
        <div class="app-kv"><span class="k">开始时间</span><span class="v">{{ current.startedAt }}</span></div>
        <div class="app-kv"><span class="k">年份</span><span class="v">{{ current.year }}</span></div>
        <div class="app-kv"><span class="k">数量</span><span class="v">{{ current.limit }}</span></div>
        <div class="app-kv"><span class="k">成功</span><span class="v">{{ successCount(current) }}</span></div>
        <div class="app-kv"><span class="k">失败</span><span class="v">{{ current.failedCount }}</span></div>
        <div class="app-kv"><span class="k">状态</span><span class="v">{{ statusTag(current.status).text }}</span></div>
        <div class="app-kv"><span class="k">结束时间</span><span class="v">{{ current.finishedAt || '—' }}</span></div>
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
