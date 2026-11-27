<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    lines: string[]
    height?: number
    emptyText?: string
    autoFollow?: boolean
    fill?: boolean
    stretch?: boolean
  }>(),
  {
    height: 240,
    emptyText: '等待任务开始…',
    autoFollow: true,
    fill: false,
    stretch: false,
  },
)

const body = ref<HTMLElement | null>(null)
const following = ref(props.autoFollow)

const showJump = computed(() => !following.value && props.lines.length > 0)

// stretch 模式由父容器决定高度，fill 模式使用固定视口高度，两者都不写内联高度
const fixedHeight = computed(() => (props.fill || props.stretch ? undefined : { height: `${props.height}px` }))

function scrollToBottom() {
  const element = body.value
  if (!element) {
    return
  }
  element.scrollTop = element.scrollHeight
  following.value = true
}

function onScroll() {
  const element = body.value
  if (!element) {
    return
  }
  const distance = element.scrollHeight - element.scrollTop - element.clientHeight
  following.value = distance < 12
}

watch(
  () => props.lines.length,
  async () => {
    if (!props.autoFollow || !following.value) {
      return
    }
    await nextTick()
    scrollToBottom()
  },
)
</script>

<template>
  <div class="log-shell" :class="{ fill, stretch }">
    <div
      ref="body"
      class="log-body"
      :style="fixedHeight"
      role="log"
      @scroll="onScroll"
    >
      <div v-for="(line, index) in lines" :key="index" class="log-line">{{ line }}</div>
      <div v-if="lines.length === 0" class="log-empty">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <rect x="3.5" y="5" width="17" height="14" rx="2.5" />
          <path d="m7.5 10 2.5 2-2.5 2" />
          <path d="M12.5 14h4" />
        </svg>
        <span>{{ emptyText }}</span>
      </div>
    </div>
    <button v-if="showJump" class="log-jump" type="button" @click="scrollToBottom">
      回到最新
    </button>
  </div>
</template>

<style scoped>
.log-shell {
  position: relative;
}

.log-shell.fill {
  display: block;
}

.log-body {
  overflow-x: hidden;
  overflow-y: auto;
  padding: 14px 16px;
  border-radius: 10px;
  background: #0f172a;
  color: #cbd5e1;
  font: 12px/1.75 Consolas, 'Cascadia Mono', monospace;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  scrollbar-color: #475569 #111827;
  scrollbar-width: thin;
}

.log-shell.fill .log-body {
  height: clamp(220px, calc(100vh - 430px), 560px);
}

/* stretch 模式：高度完全由父容器决定，用于铺满页面剩余空间 */
.log-shell.stretch {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.log-shell.stretch .log-body {
  flex: 1;
  min-height: 0;
}

.log-body::-webkit-scrollbar {
  width: 10px;
}

.log-body::-webkit-scrollbar-track {
  background: #111827;
  border-radius: 8px;
}

.log-body::-webkit-scrollbar-thumb {
  border: 2px solid #111827;
  border-radius: 8px;
  background: #475569;
}

.log-line {
  min-height: 21px;
}

.log-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  height: 100%;
  min-height: 120px;
  color: #64748b;
}

.log-empty svg {
  width: 26px;
  height: 26px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-linejoin: round;
  opacity: 0.8;
}

.log-jump {
  position: absolute;
  right: 14px;
  bottom: 12px;
  height: 28px;
  padding: 0 10px;
  border: 1px solid #334155;
  border-radius: 7px;
  background: #1e293b;
  color: #cbd5e1;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  box-shadow: 0 4px 12px rgb(2 6 23 / 28%);
}

.log-jump:hover {
  border-color: #475569;
  background: #334155;
}
</style>
