<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useSession } from '../../composables/useSession'
import { errorMessage, request } from '../../api/client'
import type { ClipDetail } from '../../types/api'
import MediaPlayer from '../common/MediaPlayer.vue'

const props = defineProps<{ id: number; range: NonNullable<ClipDetail['adjust']> }>()
const emit = defineEmits<{ saved: [] }>()
const { csrfHeaders } = useSession()
const start = ref<number | string>(props.range.start)
const end = ref<number | string>(props.range.end)
const startAt = computed(() => props.range.start)
const playingSource = ref(false)
const player = ref<InstanceType<typeof MediaPlayer>>()
const busy = ref(false)
const error = ref('')
const notice = ref('')
const valid = computed(() => start.value !== '' && end.value !== ''
  && Number(end.value) - Number(start.value) >= 0.5
  && Number(start.value) <= props.range.time && Number(end.value) >= props.range.time)

watch([() => props.range.start, () => props.range.end], ([newStart, newEnd]) => {
  start.value = newStart
  end.value = newEnd
})

function step(direction: number) {
  player.value?.element()?.pause()
  if (player.value) player.value.seek(player.value.currentTime() + direction / props.range.fps)
}

async function save() {
  if (busy.value || !valid.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await request(`/api/clips/${props.id}/range`, {
      method: 'POST', headers: { ...await csrfHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ start: Number(start.value), end: Number(end.value) }),
    })
    notice.value = 'Klip trafił do kolejki ponownego cięcia.'
    emit('saved')
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <q-expansion-item v-model="playingSource" label="Przytnij klip" icon="content_cut" class="q-my-md">
    <q-card flat bordered>
      <q-card-section>
        <q-banner v-if="error" class="error-banner q-mb-sm" role="alert">{{ error }}</q-banner>
        <p v-if="notice" role="status">{{ notice }}</p>
        <p class="muted">Ustaw granice na pełnym nagraniu. Zakres musi objąć znacznik ({{ range.time.toFixed(2) }} s).</p>
        <MediaPlayer v-if="playingSource" ref="player" :src="`/videos/${range.video_id}/stream`"
          label="Pełne nagranie do przycięcia" :start="startAt" @failed="error = 'Nie udało się otworzyć nagrania.'" />
        <div class="row items-center q-gutter-xs q-my-sm">
          <q-btn flat dense icon="skip_previous" aria-label="Klatka wstecz" @click="step(-1)" />
          <q-btn flat dense icon="skip_next" aria-label="Klatka naprzód" @click="step(1)" />
          <q-btn flat label="Ustaw początek tutaj" @click="player && (start = player.currentTime())" />
          <q-btn flat label="Ustaw koniec tutaj" @click="player && (end = player.currentTime())" />
        </div>
        <q-form class="row items-center q-gutter-sm" @submit="save">
          <q-input v-model="start" type="number" min="0" step="any" outlined dense label="Początek (s)" required :disable="busy" />
          <q-input v-model="end" type="number" min="0" step="any" outlined dense label="Koniec (s)" required :disable="busy" />
          <q-btn flat label="Podgląd zakresu" :disable="!valid" @click="player?.preview(Number(start), Number(end))" />
          <q-btn type="submit" color="primary" label="Wytnij ponownie" :disable="!valid" :loading="busy" />
        </q-form>
      </q-card-section>
    </q-card>
  </q-expansion-item>
</template>
