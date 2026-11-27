<script setup lang="ts">
withDefaults(defineProps<{
  variant?: 'list' | 'matches' | 'detail' | 'form' | 'media' | 'inline'
  label?: string
  rows?: number
}>(), {
  variant: 'list',
  label: 'Ładowanie danych',
  rows: 3,
})
</script>

<template>
  <div class="loading-skeleton" role="status">
    <span class="loading-label">{{ label }}</span>
    <div aria-hidden="true">
      <template v-if="variant === 'matches'">
        <div v-for="row in rows" :key="row" class="match-row">
          <q-skeleton class="match-icon" />
          <div class="match-info column q-gutter-y-sm">
            <q-skeleton width="32%" height="13px" />
            <q-skeleton width="68%" height="24px" />
            <q-skeleton width="52%" height="13px" />
          </div>
          <div class="match-summary">
            <q-skeleton type="QBadge" />
            <q-skeleton width="72px" height="13px" />
          </div>
        </div>
      </template>

      <div v-else-if="variant === 'list'" class="skeleton-list">
        <div v-for="row in rows" :key="row" class="skeleton-item">
          <q-skeleton width="min(65%, 320px)" height="18px" />
          <q-skeleton width="min(45%, 200px)" height="13px" />
        </div>
      </div>

      <div v-else-if="variant === 'form'" class="column q-gutter-y-md">
        <q-skeleton v-for="row in rows" :key="row" height="56px" />
        <q-skeleton type="QBtn" width="128px" />
      </div>

      <q-skeleton v-else-if="variant === 'inline'" width="min(100%, 260px)" height="36px" />

      <div v-else class="column q-gutter-y-md">
        <q-skeleton width="min(72%, 420px)" height="36px" />
        <q-skeleton width="min(55%, 260px)" height="16px" />
        <q-skeleton v-if="variant === 'media'" class="skeleton-player" />
        <div v-else class="skeleton-list">
          <div v-for="row in rows" :key="row" class="skeleton-item">
            <q-skeleton width="min(55%, 240px)" height="18px" />
            <q-skeleton width="min(78%, 440px)" height="14px" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.loading-label {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}

.skeleton-list {
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-surface);
  background: var(--surface);
}

.skeleton-item {
  display: grid;
  gap: 8px;
  padding: 16px;
}

.skeleton-item + .skeleton-item {
  border-top: 1px solid var(--surface-separator);
}

.skeleton-player {
  aspect-ratio: 16 / 9;
  max-height: 60vh;
  border-radius: var(--radius-control);
}

@media (prefers-reduced-motion: reduce) {
  .loading-skeleton :deep(.q-skeleton::after) {
    animation: none;
  }
}
</style>
