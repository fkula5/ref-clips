<script setup lang="ts">
import MediaPlayer from '../components/common/MediaPlayer.vue'
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useResource } from '../composables/useResource'
import type { SetClip } from '../types/training'

const route = useRoute()
const base = computed(() => `/sets/${route.params.id}/clips/${route.params.clipId}`)
const { data, error, loading, saving, refresh, save } = useResource<SetClip>(() => base.value)
const note = ref('')
watch(data, clip => { note.value = clip?.note ?? '' })

async function saveNote() {
  if (await save(`${base.value}/note`, { note: note.value })) refresh()
}
</script>

<template>
  <q-page class="matches-page">
    <q-btn flat :label="data?.set_name || 'Wróć do zestawu'" :to="{ name: 'set-detail', params: { id: route.params.id } }" />
    <LoadingSkeleton v-if="loading && !data" variant="media" label="Ładowanie klipu szkoleniowego" class="q-mt-md" />
    <q-banner v-if="error" class="error-banner q-my-md" role="alert">{{ error }}</q-banner>
    <template v-if="data">
      <header class="page-heading"><div><h1>{{ data.match }}</h1><p class="muted">{{ data.level }} · Klip {{ data.index }} z {{ data.total }}</p></div></header>
      <nav class="row q-gutter-sm q-mb-md" aria-label="Klipy w zestawie">
        <q-btn v-if="data.previous" outline label="Poprzedni klip" :to="{ name: 'set-clip', params: { id: data.set_id, clipId: data.previous } }" />
        <q-btn v-if="data.next" outline label="Następny klip" :to="{ name: 'set-clip', params: { id: data.set_id, clipId: data.next } }" />
      </nav>
      <MediaPlayer v-if="data.stream" :key="data.stream" :src="data.stream" label="Klip szkoleniowy" />
      <q-banner v-else class="q-mb-md">Plik klipu jest obecnie niedostępny.</q-banner>
      <div class="row q-gutter-sm q-my-md">
        <q-btn v-if="data.stream" flat color="primary" label="Pobierz MP4" :href="`${base}/download`" />
        <q-btn flat label="Szczegóły klipu" :to="{ name: 'clip-detail', params: { id: data.id } }" />
      </div>
      <q-card flat bordered>
        <q-card-section>
          <h2 class="text-h6">Opis klipu</h2>
          <div v-if="data.official || data.category" class="set-clip-info">
            <span v-if="data.category" class="info-category">{{ data.category }}</span>
            <span v-if="data.official" class="info-person">{{ data.official }}</span>
          </div>
          <p class="preserve-lines info-copy">{{ data.description }}</p>
        </q-card-section>
        <q-separator />
        <q-card-section>
          <h2 class="text-h6">Notatka szkoleniowca</h2>
          <q-form v-if="data.can_edit" @submit="saveNote">
            <q-input v-model="note" outlined type="textarea" label="Notatka" :disable="saving" />
            <q-btn type="submit" color="primary" class="q-mt-sm" label="Zapisz notatkę" :loading="saving" />
          </q-form>
          <p v-else class="preserve-lines" :class="data.note ? 'info-copy' : 'info-context'">{{ data.note || 'Brak notatki.' }}</p>
        </q-card-section>
      </q-card>
    </template>
  </q-page>
</template>

<style scoped>
.set-clip-info { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 12px; margin-bottom: 10px; }
.preserve-lines { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
