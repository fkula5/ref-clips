<script setup lang="ts">
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, errorMessage } from '../api/client'
import { fetchRecording, updateRecording } from '../api/recordings'
import type { RecordingState } from '../api/recordings'
import RecordingControls from '../components/matches/RecordingControls.vue'
import RecordingNotes from '../components/matches/RecordingNotes.vue'
import RecordingMarkers from '../components/matches/RecordingMarkers.vue'
import ConfirmAction from '../components/common/ConfirmAction.vue'
import { useSession } from '../composables/useSession'
import { useWatchRoom } from '../composables/useWatchRoom'

const route = useRoute()
const router = useRouter()
const session = useSession()
const recording = ref<RecordingState | null>(null)
const player = ref<InstanceType<typeof RecordingControls>>()
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const info = ref('')
const highlighted = ref<number>()
const quickText = ref('')
const quickTime = ref<number | null>(null)
const quickInput = ref<{ focus(): void }>()
const rangeStart = ref<number | null>(null)
const rangeEnd = ref<number | null>(null)
const cutId = ref<number>()
const removing = ref<RecordingState['clips'][number]>()
const start = computed(() => typeof route.query.t === 'string' ? Number(route.query.t) : 0)
const refresh = ref(0)
const cutPending = computed(() => recording.value?.clips.some(clip => clip.status === 'queued') ?? false)
const lastCut = computed(() => recording.value?.clips.find(clip => clip.id === cutId.value))
const hasRange = computed(() => rangeStart.value !== null && rangeEnd.value !== null
  && rangeEnd.value - rangeStart.value >= 0.5 && rangeEnd.value - rangeStart.value <= 240)
const points = computed(() => [
  ...(recording.value?.periods.flatMap(({ period, mark }) => mark
    ? [{ id: period, time: mark.time_sec, label: `Początek ${period} · ${mark.clock}`, period: true }] : []) ?? []),
  ...(recording.value?.clips.map(clip => ({
    id: `clip-${clip.id}`, time: clip.time_sec, label: `${clip.clock} · ${clip.category || 'Znacznik'}`,
  })) ?? []),
])
const {
  room, link, me, people, leader, leading, online, locked, detached, status: roomStatus, playBlocked,
  creating, create, leave, toggleDetached, handover, resume,
} = useWatchRoom(() => player.value?.element(), () => recording.value?.playable ? recording.value.video_id : undefined,
  () => { if (!busy.value && !loading.value) refresh.value++ })

async function handleError(err: unknown) {
  if (err instanceof ApiError && err.status === 401) {
    session.clear()
    await router.replace({ name: 'login', query: { next: route.fullPath.split('#')[0] }, hash: route.hash })
  } else {
    error.value = errorMessage(err)
  }
}

watch([() => route.params.id, refresh], async ([id], _, onCleanup) => {
  if (typeof id !== 'string') return
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  if (String(recording.value?.video_id) !== id) {
    recording.value = null
    quickText.value = ''
    quickTime.value = null
    clearRange()
    highlighted.value = undefined
    info.value = ''
  }
  error.value = ''
  loading.value = true
  try {
    const state = await fetchRecording(id, controller.signal)
    if (!controller.signal.aborted) recording.value = state
  } catch (err) {
    if (!controller.signal.aborted) await handleError(err)
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })

watch(cutPending, (pending, _, onCleanup) => {
  if (!pending) return
  let activePoll: AbortController | undefined
  const timer = window.setInterval(async () => {
    const previous = recording.value
    if (!previous || activePoll || document.hidden || loading.value || busy.value) return
    const controller = new AbortController()
    activePoll = controller
    try {
      const state = await fetchRecording(String(previous.video_id), controller.signal)
      if (!controller.signal.aborted && recording.value === previous && !busy.value && !loading.value) recording.value = state
    } catch {
      // Leave the last state visible and retry on the next interval.
    } finally {
      activePoll = undefined
    }
  }, 4000)
  onCleanup(() => {
    window.clearInterval(timer)
    activePoll?.abort()
  })
})

async function update(path: string, payload?: object, method = 'POST') {
  const id = recording.value?.video_id
  if (!id || busy.value || loading.value) return
  busy.value = true
  error.value = ''
  info.value = ''
  cutId.value = undefined
  try {
    const state = await updateRecording(path, await session.csrfHeaders(), payload, method)
    if (route.name !== 'recording' || route.params.id !== String(id)) return
    recording.value = state
    return state
  } catch (err) {
    if (route.name === 'recording' && route.params.id === String(id)) await handleError(err)
  } finally {
    busy.value = false
  }
}

async function marker(time: number) {
  const result = await update(`/api/videos/${recording.value?.video_id}/markers`, { time_sec: time })
  if (result?.marker) {
    highlighted.value = cutId.value = result.marker.id
    info.value = result.created ? `Znacznik zapisany w ${result.marker.clock}.` : 'Znacznik został już dodany przed chwilą.'
  }
}

async function undo() {
  if (await update(`/api/videos/${recording.value?.video_id}/markers/undo`)) info.value = 'Ostatni nieopisany znacznik został cofnięty.'
}

async function openQuick() {
  const control = player.value
  if (!control) return
  if (!locked.value) control.element()?.pause()
  quickText.value = ''
  quickTime.value = control.currentTime()
  await nextTick()
  quickInput.value?.focus()
}

async function quickClip() {
  const text = quickText.value.trim()
  if (!text || quickTime.value === null || !recording.value) return
  const result = await update(`/api/videos/${recording.value.video_id}/quick-clip`, { time_sec: quickTime.value, text })
  if (result) {
    quickText.value = ''
    quickTime.value = null
    highlighted.value = cutId.value = result.clip?.id
    info.value = ['Znacznik z notatką zapisany.', ...(result.warnings ?? [])].join(' ')
  }
}

async function setQuarter(period = recording.value?.next_period) {
  if (!recording.value || !player.value || !recording.value.can_mark) return
  if (!period) {
    info.value = 'Wszystkie wymagane kwarty są ustawione. Możesz poprawić początek w panelu kwart.'
    return
  }
  const result = await update(`/api/videos/${recording.value.video_id}/marks`, { period, time_sec: player.value.currentTime() })
  const mark = result?.periods.find(item => item.period === period)?.mark
  if (mark) info.value = `Początek ${period} ustawiony w ${mark.clock}.`
}

function jumpToQuarters() {
  document.getElementById('poczatki-kwart')?.scrollIntoView()
}

function pickRange(edge: 'start' | 'end') {
  if (locked.value || !player.value) return
  const time = player.value.currentTime()
  if (edge === 'start') rangeStart.value = time
  else rangeEnd.value = time
}

function clearRange() {
  rangeStart.value = rangeEnd.value = null
  cutId.value = undefined
}

async function cutRange() {
  if (!hasRange.value || !recording.value || locked.value) return
  const result = await update(`/api/videos/${recording.value.video_id}/clips`, { start: rangeStart.value, end: rangeEnd.value })
  if (result?.clip_id) {
    clearRange()
    highlighted.value = cutId.value = result.clip_id
    info.value = 'Zakres klipu zapisany.'
  }
}

async function removeMarker() {
  const clip = removing.value
  if (clip && await update(`/api/clips/${clip.id}?confirm=true`, undefined, 'DELETE')) removing.value = undefined
}
</script>

<template>
  <q-page class="matches-page recording-page">
    <q-btn v-if="!recording" flat color="primary" label="Wróć do meczów" :to="{ name: 'matches' }" />
    <LoadingSkeleton v-if="loading && !recording" variant="media" label="Ładowanie nagrania" class="q-my-md" />
    <q-banner v-if="error" class="error-banner q-my-md" role="alert">
      {{ error }}
      <template #action><q-btn flat label="Odśwież dane" :disable="busy" @click="refresh++" /></template>
    </q-banner>
    <template v-if="recording">
      <header class="page-heading recording-heading">
        <div><p class="muted">{{ recording.match_title }}</p><h1>{{ recording.name }}</h1><p class="muted">{{ recording.content_label }}</p></div>
        <q-btn class="recording-back" flat color="primary" icon="arrow_back" label="Wróć do meczu"
          :to="{ name: 'match-detail', params: { id: recording.match_id } }" />
      </header>
      <div class="recording-layout">
      <div v-if="recording.playable" class="recording-main">
        <RecordingControls ref="player" :key="recording.video_id" :id="recording.video_id" :name="recording.name"
          :start="start" :fps="recording.fps" :can-clip="recording.can_clip" :can-mark="recording.can_mark"
          :busy="busy || loading" :locked="locked" :points="points" :range-start="rangeStart" :range-end="rangeEnd"
          @marker="marker" @undo="undo" @quick="openQuick" @quarter="setQuarter()" @range-start="pickRange('start')"
          @range-end="pickRange('end')" @failed="error = 'Nie udało się odtworzyć nagrania.'">
          <template v-if="recording.can_clip || recording.can_mark" #default="{ ready }">
            <div class="recording-tools primary-tools">
              <q-btn v-if="recording.can_clip" class="quick-cut" color="primary" icon="content_cut"
                :label="`Wytnij −${recording.quick_cut.before} s / +${recording.quick_cut.after} s (Z)`"
                :disable="!ready || busy || loading" @click="player && marker(player.currentTime())" />
              <q-btn v-if="recording.can_clip" flat label="Cofnij znacznik" :disable="!ready || busy || loading" @click="undo" />
              <q-btn v-if="recording.can_clip" flat label="Znacznik z notatką (M)" :disable="!ready || busy || loading" @click="openQuick" />
              <q-btn v-if="recording.can_mark && recording.next_period" flat :label="`Początek ${recording.next_period} (Q)`" :disable="!ready || busy || loading" @click="setQuarter()" />
            </div>
            <q-form v-if="quickTime !== null" class="quick-note-form" @submit="quickClip" @keydown.esc.stop="quickTime = null">
              <q-input ref="quickInput" v-model="quickText" class="col" dark outlined dense label="Notatka do znacznika"
                placeholder="U1 faul techniczny" :disable="busy" />
              <q-btn type="submit" color="primary" label="Zapisz" :disable="!quickText.trim() || busy || loading" />
              <q-btn flat label="Anuluj" @click="quickTime = null" />
            </q-form>
            <div v-if="recording.can_clip" class="recording-tools range-tools">
              <q-btn outline icon="first_page" :label="rangeStart === null ? 'Początek (I)' : `Początek · ${rangeStart.toFixed(2)} s`" :disable="!ready || locked || busy" @click="pickRange('start')" />
              <q-btn outline icon="last_page" :label="rangeEnd === null ? 'Koniec (O)' : `Koniec · ${rangeEnd.toFixed(2)} s`" :disable="!ready || locked || busy" @click="pickRange('end')" />
              <q-btn flat icon="play_arrow" label="Podgląd zakresu" :disable="!hasRange || locked" @click="rangeStart !== null && rangeEnd !== null && player?.preview(rangeStart, rangeEnd)" />
              <q-btn outline icon="content_cut" label="Wytnij zakres" :disable="!hasRange || locked || busy || loading" @click="cutRange" />
              <q-btn v-if="rangeStart !== null || rangeEnd !== null" flat label="Wyczyść zakres" @click="clearRange" />
              <span v-if="rangeStart !== null && rangeEnd !== null && !hasRange" class="q-pa-xs text-caption" role="status">Zakres musi trwać od 0,5 do 240 s.</span>
            </div>
            <div v-if="info" class="recording-tools row items-center q-gutter-xs">
              <span role="status">
                {{ info }}
                <template v-if="lastCut?.status === 'queued'"> Cięcie w kolejce.</template>
                <template v-else-if="lastCut?.status === 'cut'"> Klip gotowy.</template>
                <template v-else-if="lastCut?.status === 'error'"> Cięcie nie powiodło się.</template>
              </span>
              <q-btn v-if="cutId" flat label="Otwórz klip" :to="{ name: 'clip-detail', params: { id: cutId } }" />
            </div>
          </template>
        </RecordingControls>
        <div class="row q-gutter-sm q-my-md">
          <q-btn flat color="primary" icon="flag" label="Początki kwart" @click="jumpToQuarters" />
          <q-btn v-if="recording.can_download" flat color="primary" label="Pobierz nagranie" :href="`/videos/${recording.video_id}/download`" />
          <q-btn v-if="!room" flat color="primary" label="Oglądaj razem" :loading="creating" @click="create" />
        </div>
        <q-banner v-if="!room && roomStatus" class="error-banner q-mb-md" role="status">{{ roomStatus }}</q-banner>
        <q-card v-if="room" flat bordered class="q-mb-md">
          <q-card-section>
            <h2 class="text-h6">Wspólne oglądanie</h2>
            <p role="status">{{ roomStatus }}<template v-if="leader"> · {{ leading ? 'Ty sterujesz' : `Steruje ${leader.name}` }}</template></p>
            <q-input :model-value="link" outlined readonly label="Link do pokoju" />
            <q-list v-if="people.length" separator>
              <q-item v-for="person in people" :key="person.id">
                <q-item-section>{{ person.name }}{{ person.id === me ? ' (Ty)' : '' }}</q-item-section>
                <q-item-section v-if="leading && person.id !== me && online" side>
                  <q-btn flat dense label="Przekaż sterowanie" @click="handover(person.id)" />
                </q-item-section>
              </q-item>
            </q-list>
            <div class="row q-gutter-sm q-mt-sm">
              <q-btn v-if="playBlocked && locked" color="primary" label="Włącz odtwarzanie" @click="resume" />
              <q-btn v-if="!leading && online" flat :label="detached ? 'Wróć do synchronizacji' : 'Oglądaj samodzielnie'" @click="toggleDetached" />
              <q-btn flat label="Opuść pokój" @click="leave" />
            </div>
          </q-card-section>
        </q-card>
        <RecordingNotes v-if="recording.can_clip" :key="`notes-${recording.video_id}`" :id="recording.video_id" @saved="refresh++" />
      </div>
      <q-banner v-else class="q-mb-md">Pełne nagranie jest obecnie niedostępne.</q-banner>
      <RecordingMarkers :recording="recording" :busy="busy || loading" :locked="locked" :highlighted="highlighted"
        @seek="player?.seek($event)" @mark-period="setQuarter"
        @delete-period="update(`/api/marks/${$event}`, undefined, 'DELETE')" @delete-clip="removing = $event" />
      </div>
      <ConfirmAction v-if="removing" :model-value="true" @update:model-value="!$event && (removing = undefined)"
        title="Usunąć znacznik?" message="Usunięty zostanie również powiązany klip." label="Usuń znacznik" :busy="busy" @confirm="removeMarker" />
    </template>
  </q-page>
</template>

<style scoped>
.recording-page { container: recording-page / inline-size; }
.recording-layout { display: grid; gap: 16px; align-items: start; }
.recording-main, .recording-layout > * { min-width: 0; }
.recording-tools, .quick-note-form {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 8px;
}
.recording-tools .q-btn, .quick-note-form .q-btn { min-height: 44px; }
.range-tools { border-top: 1px solid var(--player-border); }

@container recording-page (min-width: 1040px) {
  .recording-layout { grid-template-columns: minmax(0, 1fr) minmax(300px, 32%); gap: 20px; }
}

@container recording-page (max-width: 510px) {
  .recording-heading { gap: 8px; }
  .recording-heading .recording-back { order: -1; margin-inline-start: -8px; }
  .primary-tools, .range-tools { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }
  .recording-tools .q-btn { padding-inline: 4px; font-size: 0.8rem; }
  .recording-tools .quick-cut, .recording-tools > [role="status"] { grid-column: 1 / -1; }
  .quick-note-form .q-field { flex: 1 0 100%; }
}
</style>
