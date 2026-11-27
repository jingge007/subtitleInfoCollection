<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'

import { api, type ConfigField, type ConfigGroup } from '@/api/bridge'
import PageHeader from '@/components/PageHeader.vue'
import { formatEpochMillis } from '@/utils/datetime'

const loading = ref(true)
const saving = ref(false)
const groups = ref<ConfigGroup[]>([])
const values = ref<Record<string, string>>({})
const original = ref<Record<string, string>>({})
const activeGroup = ref('')

const dirtyKeys = computed(() =>
  Object.keys(values.value).filter((key) => values.value[key] !== original.value[key]),
)

const activeFields = computed<ConfigField[]>(
  () => groups.value.find((group) => group.key === activeGroup.value)?.fields ?? [],
)

// 需要额外展示可读时间的时间戳配置项
const TIMESTAMP_FIELD_KEYS = new Set(['TODAYS_LINES_TOKEN_TIME'])

// 配置项提示文案，时间戳类补充本地时间说明，配置值本身保持原样
function fieldHint(field: ConfigField): string {
  const value = values.value[field.key] ?? ''
  if (TIMESTAMP_FIELD_KEYS.has(field.key) && value) {
    return `${field.description.replace(/[。.]?$/, '')} · 对应时间 ${formatEpochMillis(value)}`
  }
  return field.description
}

async function load() {
  loading.value = true
  try {
    groups.value = await api.configList()
    const next: Record<string, string> = {}
    groups.value.forEach((group) => {
      group.fields.forEach((field) => {
        next[field.key] = field.value
      })
    })
    values.value = { ...next }
    original.value = { ...next }
    activeGroup.value = groups.value[0]?.key ?? ''
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const changed: Record<string, string> = {}
    dirtyKeys.value.forEach((key) => {
      changed[key] = values.value[key]
    })
    await api.configSave(changed)
    original.value = { ...values.value }
    ElMessage.success('配置已保存')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : String(error))
  } finally {
    saving.value = false
  }
}

async function pickPath(field: ConfigField) {
  const dir = await api.shellPickDirectory()
  if (dir) {
    values.value[field.key] = dir
  }
}

onMounted(load)
</script>

<template>
  <div>
    <PageHeader title="配置项" subtitle="读写 %APPDATA%\subtitleInfoCollection\.env，密钥仅保存在本机">
      <span v-if="dirtyKeys.length" class="app-pill">{{ dirtyKeys.length }} 项未保存</span>
      <el-button :disabled="saving" @click="load">重新加载</el-button>
      <el-button type="primary" :loading="saving" :disabled="dirtyKeys.length === 0" @click="save">保存</el-button>
    </PageHeader>

    <div v-loading="loading" class="config-layout">
      <div class="app-card group-nav">
        <button
          v-for="group in groups"
          :key="group.key"
          type="button"
          class="group-item"
          :class="{ active: activeGroup === group.key }"
          @click="activeGroup = group.key"
        >
          {{ group.label }}
        </button>
      </div>

      <div class="app-card">
        <div class="card-title">
          {{ groups.find((group) => group.key === activeGroup)?.label ?? '配置项' }}
          <span class="sub">留空表示未配置</span>
        </div>

        <div class="app-grid g2">
          <div v-for="field in activeFields" :key="field.key" class="field">
            <label>
              {{ field.label }}
              <span v-if="field.secret" class="app-tag info">密钥</span>
            </label>
            <el-switch
              v-if="field.widget === 'bool'"
              v-model="values[field.key]"
              active-value="true"
              inactive-value="false"
              active-text="开启"
              inactive-text="关闭"
            />
            <div v-else-if="field.widget === 'path'" class="path-row">
              <el-input v-model="values[field.key]" :placeholder="field.description" />
              <el-button @click="pickPath(field)">选择</el-button>
            </div>
            <el-input
              v-else
              v-model="values[field.key]"
              :type="['int', 'float', 'optional_int'].includes(field.widget) ? 'number' : 'text'"
              :placeholder="field.description"
            />
            <div v-if="values[field.key]" class="hint">{{ fieldHint(field) }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.config-layout {
  display: grid;
  grid-template-columns: 200px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.group-nav {
  padding: 8px;
  position: sticky;
  top: 0;
}

.group-item {
  display: block;
  width: 100%;
  padding: 10px 12px;
  margin-bottom: 3px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--app-text-2);
  font-size: 13px;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.group-item:hover {
  background: #f0f2f6;
}

.group-item.active {
  background: var(--app-brand-soft);
  border-color: #d6e6ff;
  color: var(--app-brand);
  font-weight: 600;
}

.field label {
  gap: 7px;
}

.hint {
  margin-top: 5px;
  font-size: 12px;
  color: var(--app-text-3);
}

.path-row {
  display: flex;
  gap: 8px;
}

@media (max-width: 900px) {
  .config-layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .group-nav {
    position: static;
    display: flex;
    gap: 4px;
    overflow-x: auto;
  }

  .group-item {
    width: auto;
    flex: 0 0 auto;
  }
}
</style>
