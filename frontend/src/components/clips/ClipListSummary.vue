<script setup lang="ts">
import type { RouteLocationRaw } from 'vue-router'

defineProps<{ time: string; title: string; match?: string; official?: string; description?: string; to?: RouteLocationRaw }>()
</script>

<template>
  <div class="clip-summary">
    <div class="clip-context">
      <span class="info-time" :title="`Czas w nagraniu: ${time}`">{{ time }}</span>
      <span v-if="match" class="info-context">{{ match }}</span>
    </div>
    <RouterLink v-if="to" class="clip-title info-link" :to="to">{{ title }}</RouterLink>
    <strong v-else class="clip-title">{{ title }}</strong>
    <span v-if="official" class="clip-official info-person">{{ official }}</span>
    <p v-if="description" class="clip-copy info-copy">{{ description }}</p>
  </div>
</template>

<style scoped>
.clip-summary { display: grid; min-width: 0; gap: 4px; }
.clip-context { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 8px; font-size: 0.83rem; }
.clip-title { justify-self: start; font-size: 1.04rem; line-height: 1.35; }
strong.clip-title { color: var(--text-strong); }
.clip-official { font-size: 0.86rem; }
.clip-copy {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  margin: 0;
  font-size: 0.94rem;
  line-height: 1.45;
}
</style>
