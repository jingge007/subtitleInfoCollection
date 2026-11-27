<script setup lang="ts">
import {
  ChatLineSquare,
  Download,
  Key,
  Odometer,
  Operation,
  Setting,
  Tickets,
  Tools,
  VideoPlay,
} from '@element-plus/icons-vue'
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import { useAppStore } from '@/stores/app'

const app = useAppStore()
const route = useRoute()

const groups = computed(() => [
  {
    label: '采集',
    items: [
      { path: '/dashboard', label: '任务中心', icon: Odometer, badge: '' },
      { path: '/collect', label: '开始采集', icon: VideoPlay, badge: '' },
      { path: '/parser', label: '字幕解析', icon: Download, badge: '' },
      { path: '/history', label: '历史记录', icon: Tickets, badge: '' },
    ],
  },
  {
    label: '自动化',
    items: [
      { path: '/automation', label: '自动化', icon: Setting, badge: '' },
      { path: '/scripts', label: '脚本中心', icon: Tools, badge: '' },
      { path: '/classic', label: '经典台词', icon: ChatLineSquare, badge: '' },
    ],
  },
])

const footerItems = computed(() => [
  { path: '/config', label: '配置项', icon: Key, badge: '' },
  {
    path: '/settings',
    label: '设置与维护',
    icon: Operation,
    badge: app.update?.available ? '1' : '',
  },
])

const isActive = (path: string) => route.path === path
</script>

<template>
  <aside class="sidebar" :class="{ collapsed: app.collapsed }">
    <nav class="nav">
      <div v-for="group in groups" :key="group.label" class="nav-group">
        <div v-show="!app.collapsed" class="nav-label">{{ group.label }}</div>
        <div v-show="app.collapsed" class="nav-sep" />
        <el-tooltip
          v-for="item in group.items"
          :key="item.path"
          :content="item.label"
          placement="right"
          :disabled="!app.collapsed"
          :show-after="120"
        >
          <router-link
            class="nav-item"
            :class="{ active: isActive(item.path) }"
            :to="item.path"
          >
            <el-icon class="ico"><component :is="item.icon" /></el-icon>
            <span v-show="!app.collapsed" class="label">{{ item.label }}</span>
            <span v-if="item.badge" class="badge" :class="{ dot: app.collapsed }">
              {{ app.collapsed ? '' : item.badge }}
            </span>
          </router-link>
        </el-tooltip>
      </div>
    </nav>

    <div class="nav-spacer" />

    <div class="nav-foot">
      <el-tooltip
        v-for="item in footerItems"
        :key="item.path"
        :content="item.label"
        placement="right"
        :disabled="!app.collapsed"
        :show-after="120"
      >
        <router-link class="nav-item" :class="{ active: isActive(item.path) }" :to="item.path">
          <el-icon class="ico"><component :is="item.icon" /></el-icon>
          <span v-show="!app.collapsed" class="label">{{ item.label }}</span>
          <span v-if="item.badge" class="badge" :class="{ dot: app.collapsed }">
            {{ app.collapsed ? '' : item.badge }}
          </span>
        </router-link>
      </el-tooltip>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: var(--sidebar-width);
  flex: 0 0 var(--sidebar-width);
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 12px 10px 12px;
  background: #fbfcfe;
  border-right: 1px solid var(--app-line);
  transition:
    width 180ms cubic-bezier(0.2, 0, 0, 1),
    flex-basis 180ms cubic-bezier(0.2, 0, 0, 1);
  overflow: hidden;
}

.sidebar.collapsed {
  padding-left: 8px;
  padding-right: 8px;
}

.nav {
  display: flex;
  flex-direction: column;
}

.nav-group + .nav-group {
  margin-top: 10px;
}

.nav-label {
  padding: 8px 10px 5px;
  font-size: 12px;
  letter-spacing: 0.5px;
  color: var(--app-text-3);
  white-space: nowrap;
}

.nav-sep {
  height: 1px;
  margin: 8px 6px;
  background: var(--app-line-soft);
}

.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  height: 40px;
  margin: 2px 0;
  padding: 0 11px;
  border: 1px solid transparent;
  border-radius: 9px;
  color: var(--app-text-2);
  font-size: 14px;
  text-decoration: none;
  white-space: nowrap;
  transition:
    background 120ms ease,
    color 120ms ease,
    border-color 120ms ease;
}

.sidebar.collapsed .nav-item {
  justify-content: center;
  padding: 0;
}

.nav-item:hover {
  background: #f1f5f9;
  color: var(--app-text);
}

.nav-item.active {
  border-color: #dbeafe;
  background: var(--app-brand-soft);
  color: var(--app-brand);
  font-weight: 600;
}

.nav-item.active::before {
  position: absolute;
  top: 9px;
  bottom: 9px;
  left: -10px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--app-brand);
  content: '';
}

.ico {
  flex: 0 0 auto;
  font-size: 17px;
}

.label {
  overflow: hidden;
  text-overflow: ellipsis;
}

.badge {
  margin-left: auto;
  padding: 0 6px;
  border-radius: 9px;
  background: var(--app-red);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  line-height: 17px;
}

.badge.dot {
  position: absolute;
  top: 6px;
  right: 7px;
  width: 8px;
  height: 8px;
  padding: 0;
  border-radius: 50%;
  font-size: 0;
}

.nav-spacer {
  flex: 1;
}

.nav-foot {
  padding-top: 8px;
  margin-top: 8px;
  border-top: 1px solid var(--app-line-soft);
}
</style>
