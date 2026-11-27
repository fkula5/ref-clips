<script setup lang="ts">
import { computed, ref } from 'vue'
import { errorMessage } from '../../api/client'
import { useSession } from '../../composables/useSession'
import type { MatchRecording } from '../../types/api'
import ConfirmAction from '../common/ConfirmAction.vue'

const props = defineProps<{ recordings: MatchRecording[] }>()
const emit = defineEmits<{ saved: [] }>()
const { submit } = useSession()
const selectedId = ref<number | null>(null)
const failedId = ref<number | null>(null)
const busy = ref(false)
const error = ref('')
const confirmation = ref(false)
const pending = ref<MatchRecording>()
const selected = computed(() => props.recordings.find(recording => recording.id === selectedId.value && recording.can_play))

function play(id: number) {
  failedId.value = null
  selectedId.value = id
}

async function change(id: number, action: 'retry' | 'delete') {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await submit(`/videos/${id}/${action}`)
    emit('saved')
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    confirmation.value = false
    busy.value = false
  }
}
</script>

<template>
  <section aria-labelledby="recordings-title">
    <h2 id="recordings-title" class="text-h6 q-mb-md">Nagrania</h2>
    <q-banner v-if="error" class="error-banner q-mb-md" role="alert">{{ error }}</q-banner>
    <p v-if="!recordings.length" class="muted">Brak nagrań.</p>
    <q-list v-else bordered separator class="rounded-borders">
      <q-item v-for="recording in recordings" :key="recording.id" class="recording-row">
        <q-item-section>
          <q-item-label>{{ recording.name }}</q-item-label>
          <q-item-label caption>{{ recording.purged ? 'Pełne nagranie zostało usunięte' : recording.status }}</q-item-label>
          <q-item-label v-if="recording.problem" caption class="text-negative">{{ recording.problem }}</q-item-label>
          <div v-if="recording.can_edit || recording.can_delete" class="row q-gutter-xs">
            <q-btn v-if="recording.can_edit" flat dense label="Edytuj nagranie" :to="{ name: 'recording-edit', params: { id: recording.id } }" />
            <q-btn v-if="recording.can_retry" flat dense color="primary" label="Ponów konwersję" :disable="busy" @click="change(recording.id, 'retry')" />
            <q-btn v-if="recording.can_delete" flat dense color="negative" label="Usuń nagranie" :disable="busy" @click="pending = recording; confirmation = true" />
          </div>
        </q-item-section>
        <q-item-section v-if="recording.can_play" side class="recording-actions">
          <q-btn dense unelevated color="primary" label="Otwórz analizę" :to="{ name: 'recording', params: { id: recording.id } }" />
          <q-btn flat dense color="primary" icon="play_arrow" label="Podgląd" :aria-pressed="selected?.id === recording.id" @click="play(recording.id)" />
        </q-item-section>
      </q-item>
    </q-list>
    <div v-if="selected" class="q-mt-md">
      <div class="row items-center justify-between q-mb-sm">
        <p class="q-mb-none">{{ selected.name }}</p>
        <q-btn flat dense color="primary" label="Otwórz analizę ze znacznikami"
          :to="{ name: 'recording', params: { id: selected.id } }" />
      </div>
      <q-banner v-if="failedId === selected.id" class="error-banner" role="alert">
        Nie udało się odtworzyć nagrania.
      </q-banner>
      <video
        v-else
        :key="selected.id"
        :src="`/videos/${selected.id}/stream`"
        :aria-label="selected.name"
        class="recording-player"
        controls
        playsinline
        preload="metadata"
        @error="failedId = selected.id"
      />
    </div>
    <ConfirmAction v-if="pending" v-model="confirmation" title="Usunąć nagranie?" message="Klipy wycięte z tego nagrania zostaną usunięte." label="Usuń nagranie" :busy="busy" @confirm="change(pending.id, 'delete')" />
  </section>
</template>

<style scoped>
.recording-player {
  display: block;
  width: 100%;
  max-height: 65vh;
  background: var(--player-frame);
  border-radius: var(--radius-control);
}

.recording-actions { gap: 4px; }
@media (max-width: 599px) {
  .recording-row { display: grid; gap: 10px; }
  .recording-actions { flex-direction: row; flex-wrap: wrap; justify-content: flex-start; padding-left: 0; }
  .recording-actions .q-btn { min-height: 44px; padding-inline: 10px; }
}
</style>
