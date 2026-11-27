<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Calendar,
  Collection,
  DataAnalysis,
  Delete,
  FolderOpened,
  Refresh,
} from '@element-plus/icons-vue'
import type { Component } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '@/api/bridge'
import PageHeader from '@/components/PageHeader.vue'
import { useAppStore } from '@/stores/app'

const router = useRouter()
const app = useAppStore()

interface ScriptItem {
  key: string
  title: string
  desc: string
  icon: Component
  action: string
  primary?: boolean
  danger?: boolean
}

const scripts: ScriptItem[] = [
  { key: 'today', title: '今日台词', desc: '抓取当天台词并翻译补齐', icon: Calendar, action: '进入', primary: true },
  { key: 'classic', title: '经典台词', desc: '全量抓取经典台词库', icon: Collection, action: '进入', primary: true },
  { key: 'dashboard', title: '运行总览', desc: '查看最近采集统计与失败情况', icon: DataAnalysis, action: '进入', primary: true },
  { key: 'open-data', title: '打开数据目录', desc: '打开字幕、解析结果与数据库所在目录', icon: FolderOpened, action: '打开目录' },
  { key: 'reset-history', title: '重置历史', desc: '只清空采集记录，保留 output 文件', icon: Refresh, action: '重置' },
  { key: 'clean-output', title: '清理输出', desc: '删除 output 并清空历史，不可撤销', icon: Delete, action: '执行清理', danger: true },
]

async function run(key: string) {
  try {
    if (key === 'today') {
      await router.push('/automation')
      return
    }
    if (key === 'classic') {
      await router.push('/classic')
      return
    }
    if (key === 'dashboard') {
      await router.push('/dashboard')
      return
    }
    if (key === 'open-data') {
      const info = await app.loadInfo()
      await api.shellOpenPath(info.dataDir)
      return
    }
    if (key === 'reset-history') {
      await ElMessageBox.confirm('将清空采集历史记录，但保留 output 文件，是否继续？', '重置历史', {
        confirmButtonText: '重置',
        cancelButtonText: '取消',
        type: 'warning',
      })
      await api.historyReset()
      ElMessage.success('历史记录已重置')
      return
    }
    if (key === 'clean-output') {
      await ElMessageBox.confirm(
        '将删除 output 目录并清空采集历史，此操作不可撤销，是否继续？',
        '清理输出文件',
        {
          confirmButtonText: '删除',
          cancelButtonText: '取消',
          type: 'error',
        },
      )
      await api.shellDeleteOutputs()
      ElMessage.success('输出文件与历史记录已清理')
    }
  } catch (error) {
    if (error === 'cancel' || error === 'close') {
      return
    }
    ElMessage.error(error instanceof Error ? error.message : String(error))
  }
}
</script>

<template>
  <div>
    <PageHeader title="脚本中心" subtitle="常用维护与自动化入口，危险操作均需二次确认" />

    <div class="app-grid g3">
      <div v-for="item in scripts" :key="item.key" class="app-card script-card">
        <div class="script-icon" :class="{ danger: item.danger }">
          <el-icon><component :is="item.icon" /></el-icon>
        </div>
        <div class="card-title">{{ item.title }}</div>
        <p class="script-desc">{{ item.desc }}</p>
        <el-button
          size="small"
          :type="item.primary ? 'primary' : item.danger ? 'danger' : 'default'"
          :plain="Boolean(item.danger)"
          @click="run(item.key)"
        >
          {{ item.action }}
        </el-button>
      </div>
    </div>

    <div class="app-card" style="margin-top: 12px">
      <div class="card-title">维护提示</div>
      <div class="tips">
        <div>· 清理 output 只影响采集下载目录，不会删除解析结果 automation 目录。</div>
        <div>· 配置中的密钥只保存在本机 `.env`，不会随公开仓库或安装包发布。</div>
        <div>· 自动化任务运行期间，重置历史与清理输出会被后端拒绝，请先停止任务。</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.script-card {
  display: flex;
  flex-direction: column;
  min-height: 184px;
  transition:
    border-color 120ms ease,
    box-shadow 120ms ease;
}

.script-card:hover {
  border-color: #dbeafe;
  box-shadow: 0 8px 24px rgb(37 99 235 / 7%);
}

.script-desc {
  flex: 1;
  margin: 0 0 16px;
  color: var(--app-text-3);
  font-size: 13px;
  line-height: 1.7;
}

.script-icon {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  margin-bottom: 12px;
  border-radius: 9px;
  background: var(--app-brand-soft);
  color: var(--app-brand);
  font-size: 18px;
  font-weight: 700;
}

.script-icon.danger {
  background: #fef2f2;
  color: var(--app-red);
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
