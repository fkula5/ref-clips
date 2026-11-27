<script setup lang="ts">
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useResource } from '../composables/useResource'
import ClipDescriptionForm from '../components/clips/ClipDescriptionForm.vue'
import MediaPlayer from '../components/common/MediaPlayer.vue'
import type { ClipDetail, SelectOption } from '../types/api'

interface QueueData {
  match: { id: number; title: string }
  length: number
  position: number | null
  next_id: number | null
  recordings: SelectOption[]
  current: {
    id: number; time: string; editor: NonNullable<ClipDetail['editor']>;
    preview: { kind: 'none' | 'file' | 'draft'; src?: string; start?: number; end?: number };
    problem: { message: string } | null; proposal: string
  } | null
}

const route = useRoute()
const router = useRouter()
const { data, loading, error, refresh } = useResource<QueueData>(() => {
  const params = new URLSearchParams()
  for (const name of ['clip', 'video_id']) {
    const value = route.query[name]
    if (typeof value === 'string' && value) params.set(name, value)
  }
  return `/matches/${route.params.id}/describe?${params}`
})
const player = ref<InstanceType<typeof MediaPlayer>>()

async function next() {
  const id = data.value?.next_id
  if (id) await router.replace({ query: { ...route.query, clip: String(id) } })
  else if (route.query.clip) await router.replace({ query: { ...route.query, clip: undefined } })
  else refresh()
}

function seekStart() {
  const start = data.value?.current?.preview.start
  if (start !== undefined) player.value?.seek(start)
}

function pauseAtEnd(time: number) {
  const end = data.value?.current?.preview.end
  if (end !== undefined && time >= end) player.value?.element()?.pause()
}
</script>

<template>
  <q-page class="matches-page">
    <q-btn flat label="Wróć do meczu" :to="{ name: 'match-detail', params: { id: route.params.id } }" />
    <header class="page-heading"><div><h1>Opisywanie znaczników</h1><p v-if="data">{{ data.match.title }}</p></div></header>
    <LoadingSkeleton v-if="loading && !data" variant="media" label="Ładowanie kolejki opisywania" />
    <q-banner v-if="error" class="error-banner q-my-md" role="alert">{{ error }}</q-banner>
    <template v-if="data">
      <q-select v-if="data.recordings.length > 1" :model-value="typeof route.query.video_id === 'string' ? route.query.video_id : ''" :options="[{ value: '', label: 'Wszystkie nagrania' }, ...data.recordings]" emit-value map-options outlined label="Nagranie" class="q-mb-md" @update:model-value="video_id => router.replace({ query: { video_id: video_id || undefined } })" />
      <p v-if="!data.current" class="muted">Brak znaczników do opisania.</p>
      <q-card v-else flat bordered>
        <q-card-section>
          <h2 class="text-h6">{{ data.current.time }} <span v-if="data.position" class="muted">· {{ data.position }} z {{ data.length }}</span></h2>
          <q-banner v-if="data.current.problem" class="error-banner q-mb-md">{{ data.current.problem.message }}</q-banner>
          <MediaPlayer v-if="data.current.preview.src" ref="player" :key="`${data.current.id}-${data.current.preview.src}`"
            :src="data.current.preview.src" :start="data.current.preview.start" label="Podgląd klipu do opisania"
            @time="pauseAtEnd" />
          <q-btn v-if="data.current.preview.start !== undefined" flat label="Przewiń do początku klipu" @click="seekStart" />
          <p v-if="data.current.proposal" class="muted q-mt-sm">{{ data.current.proposal }}</p>
        </q-card-section>
        <q-card-section>
          <ClipDescriptionForm :key="data.current.id" :id="data.current.id" :editor="data.current.editor" shortcuts @saved="next" />
          <q-btn v-if="data.next_id && data.next_id !== data.current.id" flat class="q-mt-sm" label="Pomiń i przejdź dalej" @click="next" />
        </q-card-section>
      </q-card>
    </template>
  </q-page>
</template>

