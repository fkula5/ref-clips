<script setup lang="ts">
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import ClipListSummary from '../components/clips/ClipListSummary.vue'
import { useRoute, useRouter } from 'vue-router'
import { useResource } from '../composables/useResource'
import type { GroupReview } from '../types/training'

const route = useRoute()
const router = useRouter()
const { data, loading, error } = useResource<GroupReview>(() => {
  const page = typeof route.query.page === 'string' ? route.query.page : '1'
  return `/groups/${route.params.id}/review?${new URLSearchParams({ page })}`
})
</script>

<template>
  <q-page class="matches-page">
    <q-btn flat label="Wróć do grupy" :to="{ name: 'group-detail', params: { id: route.params.id } }" />
    <header class="page-heading"><div><h1>Klipy do oceny</h1><p v-if="data">{{ data.group.name }}</p></div></header>
    <LoadingSkeleton v-if="loading && !data" variant="list" label="Ładowanie klipów do oceny" />
    <q-banner v-if="error" class="error-banner q-my-md" role="alert">{{ error }}</q-banner>
    <template v-if="data">
      <p v-if="!data.items.length" class="muted">Nie ma klipów czekających na Twoją ocenę.</p>
      <q-list v-else bordered separator class="surface-panel rounded-borders">
        <q-item v-for="clip in data.items" :key="clip.id" clickable :to="{ name: 'clip-detail', params: { id: clip.id }, hash: '#oceny' }">
          <q-item-section>
            <ClipListSummary :time="clip.time" :match="clip.match" :official="clip.official"
              :title="clip.category || 'Klip'" :description="clip.description" />
          </q-item-section>
        </q-item>
      </q-list>
      <q-pagination v-if="data.pages > 1" class="q-mt-md" :model-value="data.page" :max="data.pages" boundary-numbers @update:model-value="page => router.replace({ query: { page: String(page) } })" />
    </template>
  </q-page>
</template>
