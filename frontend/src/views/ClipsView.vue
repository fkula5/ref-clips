<script setup lang="ts">
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import ResponsiveFilters from '../components/common/ResponsiveFilters.vue'
import ClipListSummary from '../components/clips/ClipListSummary.vue'
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchLibrary } from '../api/clips'
import { ApiError, errorMessage } from '../api/client'
import { useSession } from '../composables/useSession'
import type { ClipLibrary } from '../types/api'

const labels = {
  match_id: 'Mecz',
  person: 'Sędzia',
  category_id: 'Kategoria',
  period: 'Kwarta',
  described: 'Opis klipu',
  rating: 'Ocena',
  group: 'Grupa szkoleniowa',
}
const route = useRoute()
const router = useRouter()
const session = useSession()
const filters = reactive<Record<string, string | null>>({})
const library = ref<ClipLibrary | null>(null)
const error = ref('')
const loading = ref(false)
const refresh = ref(0)
const selected = ref<number[]>([])
const shareDays = ref<number>()
const shareLink = ref('')
const sharing = ref(false)
const shareError = ref('')
const selectedItems = computed(() => library.value?.items.filter(item => selected.value.includes(item.id)) ?? [])
const canShare = computed(() => selectedItems.value.length > 0
  && selectedItems.value.length <= (library.value?.share_limit ?? 0)
  && selectedItems.value.every(item => item.shareable))
const exportLink = computed(() => {
  const params = new URLSearchParams()
  selectedItems.value.filter(item => item.exportable).forEach(item => params.append('ids', String(item.id)))
  return params.size ? `/clips/export.zip?${params}` : ''
})

async function createShare() {
  if (!canShare.value || !shareDays.value || sharing.value) return
  sharing.value = true
  shareError.value = ''
  shareLink.value = ''
  try {
    const fields = new URLSearchParams({ days: String(shareDays.value) })
    selectedItems.value.forEach(clip => fields.append('clip_ids', String(clip.id)))
    const result = await session.submit<{ url: string }>('/share-links', fields)
    shareLink.value = result.url
  } catch (err) {
    shareError.value = errorMessage(err)
  } finally {
    sharing.value = false
  }
}

watch([() => route.query, refresh], async ([query], _, onCleanup) => {
  if (route.name !== 'clips') return
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  const params = new URLSearchParams()
  for (const name of [...Object.keys(labels), 'since', 'page', 'video_id']) {
    const value = query[name]
    if (name !== 'page') filters[name] = typeof value === 'string' ? value : null
    if (typeof value === 'string' && value) params.set(name, value)
  }
  loading.value = true
  error.value = ''
  selected.value = []
  try {
    const result = await fetchLibrary(params, controller.signal)
    if (!controller.signal.aborted) {
      library.value = result
      shareDays.value ??= result.share_days[0]
    }
  } catch (err) {
    if (controller.signal.aborted) return
    if (err instanceof ApiError && err.status === 401) {
      session.clear()
      await router.replace({ name: 'login', query: { next: route.fullPath } })
    } else {
      error.value = errorMessage(err)
    }
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })

function apply() {
  const query = Object.fromEntries(Object.entries(filters).filter(([, value]) => value))
  const target = { name: 'clips', query }
  if (router.resolve(target).fullPath === route.fullPath) refresh.value++
  else void router.push(target)
}

function changePage(page: number) {
  return router.push({ query: { ...route.query, page: page > 1 ? String(page) : undefined } })
}
</script>

<template>
  <q-page class="matches-page">
    <header class="page-heading">
      <h1>Klipy</h1>
      <q-btn flat color="primary" label="Pełna biblioteka klipów" href="/clips?view=classic" />
    </header>
    <ResponsiveFilters v-slot="{ close }" class="clip-filters q-mb-md">
      <q-form class="q-pa-sm" @submit="apply(); close()">
        <div class="filter-grid">
          <q-select v-for="(label, name) in labels" :key="name" v-model="filters[name]" :options="library?.options[name] ?? []" :label="label" clearable outlined dense emit-value map-options />
          <q-input v-model="filters.since" type="date" label="Data meczu od" stack-label outlined dense />
        </div>
        <div class="filter-actions">
          <q-btn type="submit" color="primary" label="Filtruj" :loading="loading" />
          <q-btn flat label="Wyczyść" :to="{ name: 'clips' }" @click="close()" />
        </div>
      </q-form>
    </ResponsiveFilters>
    <LoadingSkeleton v-if="loading" variant="list" label="Ładowanie biblioteki klipów" />
    <q-banner v-else-if="error" class="error-banner" role="alert">
      {{ error }}
      <template #action><q-btn flat label="Ponów" @click="refresh++" /></template>
    </q-banner>
    <template v-else-if="library">
      <p v-if="!library.total" class="muted">Brak klipów dla wybranych filtrów.</p>
      <template v-else>
        <p class="info-context">Liczba wyników: {{ library.total }}</p>
        <q-card v-if="selected.length" flat bordered class="q-mb-md">
          <q-card-section>
            <div class="row items-center q-gutter-sm">
              <span>Zaznaczone: {{ selected.length }}</span>
              <q-select v-if="canShare" v-model="shareDays" :options="library.share_days" dense outlined label="Ważność (dni)" />
              <q-btn v-if="canShare" color="primary" label="Udostępnij wybrane" :loading="sharing" @click="createShare" />
              <q-btn v-if="library.can_export && exportLink" outline label="Pobierz wybrane jako ZIP" :href="exportLink" />
              <q-btn flat label="Wyczyść zaznaczenie" @click="selected = []" />
            </div>
            <q-banner v-if="shareError" class="error-banner q-mt-sm" role="alert">{{ shareError }}</q-banner>
            <q-input v-if="shareLink" :model-value="shareLink" readonly outlined label="Skopiuj link" class="q-mt-md" />
          </q-card-section>
        </q-card>
        <q-list bordered separator class="surface-panel rounded-borders">
          <q-item v-for="clip in library.items" :key="clip.id" class="clip-result"
            :class="{ 'clip-selectable': clip.shareable || (library.can_export && clip.exportable) }">
            <q-item-section v-if="clip.shareable || (library.can_export && clip.exportable)" side class="clip-selection">
              <q-checkbox v-model="selected" :val="clip.id" :aria-label="`Zaznacz klip ${clip.time}, ${clip.match.title}`" />
            </q-item-section>
            <q-item-section>
              <ClipListSummary
                :time="clip.time" :match="clip.match.title" :official="clip.official" :description="clip.description"
                :title="clip.category || (clip.described ? 'Klip' : 'Znacznik do opisania')"
                :to="{ name: 'clip-detail', params: { id: clip.id }, query: route.query }" />
            </q-item-section>
            <q-item-section side class="clip-result-meta">
              <q-badge class="state-badge" :data-status="clip.status_key" :label="clip.status" />
              <span class="q-mt-xs text-caption info-context">Oceny {{ clip.ratings }} · Komentarze {{ clip.comments }}</span>
            </q-item-section>
          </q-item>
        </q-list>
        <q-input v-if="shareLink && !selected.length" :model-value="shareLink" readonly outlined label="Skopiuj link" class="q-mt-md" />
        <q-pagination v-if="library.pages > 1" class="q-mt-lg" :model-value="library.page" :max="library.pages" :max-pages="5" :disable="loading" boundary-numbers @update:model-value="changePage" />
      </template>
    </template>
  </q-page>
</template>

<style scoped>
.clip-filters {
  border: 1px solid var(--surface-border);
  background: var(--surface);
  border-radius: var(--radius-surface);
  padding: 6px;
}
.clip-result { padding-block: 14px; }
.clip-result-meta { align-self: flex-start; }

@media (max-width: 599px) {
  .clip-result { display: grid; grid-template-columns: minmax(0, 1fr); gap: 8px; }
  .clip-selectable { grid-template-columns: auto minmax(0, 1fr); }
  .clip-selection { grid-row: 1 / 3; align-self: start; padding: 0; }
  .clip-result-meta {
    grid-column: -2 / -1;
    flex-direction: row;
    flex-wrap: wrap;
    align-items: center;
    justify-content: flex-start;
    gap: 6px 8px;
    padding: 0;
  }
  .clip-result-meta .text-caption { margin: 0; }
}
</style>
