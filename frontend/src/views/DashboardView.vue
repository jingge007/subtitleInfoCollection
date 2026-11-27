<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api, type HistoryItem } from '@/api/bridge'
import PageHeader from '@/components/PageHeader.vue'
import { useAppStore } from '@/stores/app'
import { formatDateTime } from '@/utils/datetime'

const app = useAppStore()
const router = useRouter()

const loading = ref(true)
const records = ref<HistoryItem[]>([])

const latest = computed(() => records.value[0])
const totalMovies = computed(() => latest.value?.movieCount ?? 0)
const successCount = computed(() => latest.value?.downloadCount ?? 0)
const failedCount = computed(() => latest.value?.failedCount ?? 0)
const successRate = computed(() =>
  totalMovies.value > 0
    ? Math.min(100, (successCount.value / totalMovies.value) * 100).toFixed(1)
    : '0.0',
)

const dataDir = computed(() => app.info?.dataDir ?? '加载中…')
const quickYear = computed(() => latest.value?.year ?? 2026)
const quickLimit = computed(() => latest.value?.limit ?? 50)

onMounted(async () => {
  try {
    const page = await api.historyList(1, 6)
    records.value = page.items
  } finally {
    loading.value = false
  }
})

function goHistory(keyword = '') {
  void router.push({ path: '/history', query: keyword ? { keyword } : {} })
}
</script>

<template>
  <div>
    <PageHeader title="任务中心" subtitle="最近一次运行状态、关键指标与快捷入口">
      <el-button @click="api.shellOpenPath(dataDir)">打开输出目录</el-button>
    </PageHeader>

    <div class="app-grid g4">
      <button class="stat" type="button" @click="goHistory(latest ? String(latest.year) : '')">
        <div class="k">电影总数</div>
        <div class="v">{{ totalMovies }}</div>
        <div class="d">{{ latest ? `${latest.year} 年榜单` : '暂无记录' }}</div>
      </button>
      <button class="stat" type="button" @click="goHistory('success')">
        <div class="k">下载成功</div>
        <div class="v green">{{ successCount }}</div>
        <div class="d">占比 {{ successRate }}%</div>
      </button>
      <button class="stat" type="button" @click="goHistory('failed')">
        <div class="k">失败</div>
        <div class="v red">{{ failedCount }}</div>
        <div class="d">可重跑失败项</div>
      </button>
      <button class="stat" type="button" @click="goHistory()">
        <div class="k">最近运行</div>
        <div class="v small mono">{{ formatDateTime(latest?.startedAt) }}</div>
        <div class="d">点击查看全部记录</div>
      </button>
    </div>

    <div class="app-cols" style="margin-top: 12px">
      <div class="app-card">
        <div class="card-title">快捷开始<span class="sub">常用参数</span></div>
        <div class="field">
          <label>年份</label>
          <el-input :model-value="String(quickYear)" readonly />
        </div>
        <div class="field">
          <label>采集数量</label>
          <el-input :model-value="String(quickLimit)" readonly />
        </div>
        <div class="field">
          <label>字幕源</label>
          <div class="source-note">
            使用「配置项 → 字幕源策略」中的启用列表与优先级，进入采集页后可临时调整。
          </div>
        </div>
        <el-button type="primary" style="width: 100%" @click="router.push('/collect')">开始采集</el-button>
      </div>

      <div class="app-card">
        <div class="card-title">最近运行<span class="sub">近 6 次</span></div>
        <el-skeleton v-if="loading" :rows="4" animated />
        <template v-else>
          <div v-for="item in records" :key="item.id" class="list-row">
            <div class="grow">
              <div class="name">{{ item.year }} 年 · {{ item.limit }} 部</div>
              <div class="path mono">{{ formatDateTime(item.startedAt) }}</div>
            </div>
            <span class="app-tag" :class="item.failedCount > 0 ? 'fail' : 'ok'">
              {{ item.failedCount > 0 ? '部分失败' : '成功' }}
            </span>
            <el-button link size="small" @click="goHistory()">详情</el-button>
          </div>
          <div v-if="records.length === 0" class="empty">暂无采集记录</div>
        </template>

        <div class="divider" />
        <div class="app-kv"><span class="k">数据目录</span><span class="v mono" :title="dataDir">{{ dataDir }}</span></div>
        <div class="app-kv"><span class="k">配置文件</span><span class="v mono">{{ app.info?.envPath ?? '加载中…' }}</span></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stat {
  display: block;
  width: 100%;
  text-align: left;
  padding: 18px 20px;
  border: 1px solid var(--app-line);
  border-radius: var(--app-radius);
  background: #fff;
  font-family: inherit;
  cursor: pointer;
  box-shadow: 0 1px 2px rgb(15 23 42 / 3%);
  transition:
    border-color 120ms ease,
    transform 120ms ease,
    box-shadow 120ms ease;
}

.stat:hover {
  border-color: #bfdbfe;
  box-shadow: 0 8px 24px rgb(37 99 235 / 8%);
  transform: translateY(-1px);
}

.stat .k {
  font-size: 12px;
  color: var(--app-text-3);
}

.stat .v {
  margin-top: 4px;
  font-size: 28px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.4px;
  color: var(--app-text);
}

.stat .v.small {
  font-size: 16px;
  line-height: 1.9;
}

.stat .v.green {
  color: var(--app-green);
}

.stat .v.red {
  color: var(--app-red);
}

.stat .d {
  margin-top: 4px;
  font-size: 12px;
  color: var(--app-text-3);
}

.source-note {
  padding: 10px 12px;
  border: 1px solid var(--app-line-soft);
  border-radius: 8px;
  background: #f8fafc;
  color: var(--app-text-3);
  font-size: 12px;
  line-height: 1.7;
}

.list-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 0;
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

.list-row .path {
  font-size: 12px;
  color: var(--app-text-3);
}

</style>
