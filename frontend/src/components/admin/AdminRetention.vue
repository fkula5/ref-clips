<script setup lang="ts">
import LoadingSkeleton from '../common/LoadingSkeleton.vue'
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useResource } from '../../composables/useResource'
import ConfirmAction from '../common/ConfirmAction.vue'

const labels = {
  drafts: 'Pełne nagrania', originals: 'Oryginały i przesyłane pliki', clips: 'Klipy',
  free: 'Wolne miejsce', total: 'Pojemność dysku', reserved: 'Zarezerwowane', acceptable: 'Limit najbliższego uploadu',
}

interface Video {
  id: number; name: string; match_id: number; match: string; status: string; uploaded: string;
  expires: string; size: number; clips: number; pending: number; blocker: string | null
}

interface RetentionData {
  days: number; min: number; max: number; page: number; pages: number; total: number;
  last_run: string; last_summary: string; usage: Record<keyof typeof labels, number>;
  rejections: { id: number; date: string; name: string; filename: string; size: number; free: number }[];
  items: Video[]
}

const route = useRoute()
const router = useRouter()
const { data, error, loading, saving, refresh, save } = useResource<RetentionData>(() => {
  const page = typeof route.query.page === 'string' ? route.query.page : '1'
  return `/admin/retention?${new URLSearchParams({ page })}`
})
const days = ref<number>()
const recalculate = ref(false)
const confirmRecalculate = ref(false)
const confirmPurge = ref(false)
const pending = ref<Video>()
const notice = ref('')
const formatter = new Intl.NumberFormat('pl-PL', { maximumFractionDigits: 2 })
const size = (bytes: number) => `${formatter.format(bytes / 1024 ** 3)} GB`

watch(data, value => { if (value) days.value = value.days })

async function change(path: string, fields: Record<string, string> = {}) {
  const result = await save<{ notice: string }>(path, fields)
  if (result) { notice.value = result.notice; refresh() }
}

async function saveDays() {
  if (days.value === undefined) return
  await change('/admin/retention', { days: String(days.value), recalculate: recalculate.value ? '1' : '0' })
  confirmRecalculate.value = false
}

async function purge() {
  if (!pending.value) return
  await change(`/admin/videos/${pending.value.id}/purge`)
  confirmPurge.value = false
}
</script>

<template>
  <section>
    <h2 class="text-h5 q-mb-md">Retencja i dysk</h2>
    <LoadingSkeleton v-if="loading && !data" variant="detail" label="Ładowanie ustawień retencji" />
    <q-banner v-if="error" class="error-banner q-my-md" role="alert">{{ error }}</q-banner>
    <q-banner v-if="notice" class="notice-success q-my-md" role="status">{{ notice }}</q-banner>
    <template v-if="data">
      <q-card flat bordered class="q-mb-lg">
        <q-card-section>
          <h3 class="text-h6">Retencja pełnych nagrań</h3>
          <q-form class="q-gutter-sm" @submit="recalculate ? confirmRecalculate = true : saveDays()">
            <q-input v-model.number="days" outlined type="number" label="Liczba dni od przesłania" :min="data.min" :max="data.max" required />
            <q-checkbox v-model="recalculate" label="Przelicz termin dla istniejących nagrań" />
            <q-btn type="submit" color="primary" label="Zapisz" :loading="saving" />
          </q-form>
          <p v-if="data.last_run" class="muted q-mt-md q-mb-none">Ostatnie sprzątanie: {{ data.last_run }}. {{ data.last_summary }}</p>
        </q-card-section>
        <q-separator />
        <q-card-section>
          <h3 class="text-h6">Zajętość dysku</h3>
          <q-list separator>
            <q-item v-for="(label, key) in labels" :key="key">
              <q-item-section>{{ label }}</q-item-section><q-item-section side>{{ size(data.usage[key]) }}</q-item-section>
            </q-item>
          </q-list>
        </q-card-section>
        <q-separator v-if="data.rejections.length" />
        <q-card-section v-if="data.rejections.length">
          <h3 class="text-h6">Przesyłanie odrzucone z braku miejsca</h3>
          <q-list separator>
            <q-item v-for="row in data.rejections" :key="row.id">
              <q-item-section><q-item-label>{{ row.filename || 'Plik' }} · {{ row.name }}</q-item-label><q-item-label caption>{{ row.date }} · Rozmiar {{ size(row.size) }} · Wolne {{ size(row.free) }}</q-item-label></q-item-section>
            </q-item>
          </q-list>
        </q-card-section>
      </q-card>
      <h3 class="text-h6">Nagrania ({{ data.total }})</h3>
      <q-list v-if="data.items.length" bordered separator class="surface-panel rounded-borders">
        <q-item v-for="video in data.items" :key="video.id">
          <q-item-section>
            <RouterLink :to="{ name: 'match-detail', params: { id: video.match_id } }">{{ video.match }}</RouterLink>
            <q-item-label>{{ video.name }} · {{ video.status }} · {{ size(video.size) }}</q-item-label>
            <q-item-label caption>{{ video.clips }} klipów · {{ video.pending }} w kolejce · Wgrano {{ video.uploaded }} · Termin {{ video.expires || 'bez terminu' }}</q-item-label>
            <q-item-label v-if="video.blocker" caption>{{ video.blocker }}</q-item-label>
            <div v-else><q-btn flat dense color="negative" label="Usuń pełne nagranie" @click="pending = video; confirmPurge = true" /></div>
          </q-item-section>
        </q-item>
      </q-list>
      <q-pagination v-if="data.pages > 1" class="q-mt-md" :model-value="data.page" :max="data.pages" boundary-numbers @update:model-value="page => router.replace({ query: { page: String(page) } })" />
    </template>
    <ConfirmAction v-model="confirmRecalculate" title="Przeliczyć istniejące terminy?" message="Nagrania po nowym terminie zostaną usunięte przy najbliższym sprzątaniu." label="Przelicz" :busy="saving" @confirm="saveDays" />
    <ConfirmAction v-if="pending" v-model="confirmPurge" title="Usunąć pełne nagranie?" :message="pending.name" label="Usuń nagranie" :busy="saving" @confirm="purge" />
  </section>
</template>
