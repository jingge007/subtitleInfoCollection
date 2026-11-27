<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
}>()
</script>

<template>
  <div class="page-header">
    <div class="titles">
      <h2>{{ title }}</h2>
      <p v-if="subtitle">{{ subtitle }}</p>
    </div>
    <div class="actions">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 20px;
}

.titles h2 {
  margin: 0 0 4px;
  font-size: 22px;
  line-height: 1.35;
  letter-spacing: -0.2px;
}

.titles p {
  margin: 0;
  max-width: 760px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--app-text-3);
}

.actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

@media (max-width: 760px) {
  .page-header {
    flex-direction: column;
  }

  .actions {
    width: 100%;
    margin-left: 0;
    justify-content: flex-start;
  }
}
</style>
