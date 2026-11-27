<script setup lang="ts">
import { computed } from 'vue'
import type { RecordingClip, RecordingState } from '../../api/recordings'

const props = defineProps<{ recording: RecordingState; busy: boolean; locked: boolean; highlighted?: number }>()
defineEmits<{
  seek: [time: number]
  markPeriod: [period: string]
  deletePeriod: [id: number]
  deleteClip: [clip: RecordingClip]
}>()

const undescribed = computed(() => props.recording.clips.filter(clip => !clip.described).length)
const cutStatus = { new: 'Do wycięcia', queued: 'W kolejce', cut: 'Wycięty', error: 'Błąd cięcia' }
</script>

<template>
  <q-card flat bordered>
    <q-card-section id="poczatki-kwart" class="period-section">
      <h2 class="text-h6">Początki kwart</h2>
      <p v-if="recording.missing_periods.length" class="muted">
        Do ustawienia: {{ recording.missing_periods.join(', ') }}. Klipy możesz wycinać w trakcie.
      </p>
      <ul class="period-list">
        <li v-for="{ period, mark, required } in recording.periods" :key="period"
          :class="{ 'next-period': period === recording.next_period }">
          <strong>{{ period }}</strong>
          <q-btn v-if="mark && recording.playable" flat dense :label="mark.clock" :disable="locked"
            :aria-label="`Przewiń do początku ${period}, ${mark.clock}`" @click="$emit('seek', mark.time_sec)" />
          <span v-else class="muted">{{ mark?.clock ?? (required ? 'Nie ustawiono' : 'Opcjonalna') }}</span>
          <q-btn v-if="recording.can_mark && recording.playable" flat dense color="primary"
            :label="mark ? 'Przestaw' : 'Ustaw tutaj'" :title="`Ustaw początek ${period} w aktualnej pozycji nagrania`"
            :disable="busy" @click="$emit('markPeriod', period)" />
          <q-btn v-if="recording.can_mark && recording.playable && mark && !recording.single_period"
            flat round dense color="negative" icon="delete_outline" :title="`Usuń początek ${period}`"
            :aria-label="`Usuń początek ${period}`" :disable="busy" @click="$emit('deletePeriod', mark.id)" />
        </li>
      </ul>
    </q-card-section>
    <q-separator />
    <q-card-section>
      <div class="row items-center justify-between q-gutter-sm">
        <h2 class="text-h6 q-mb-none">Znaczniki ({{ recording.clips.length }})</h2>
        <q-btn v-if="recording.can_clip && undescribed" flat color="primary" :label="`Opisz znaczniki (${undescribed})`"
          :to="{ name: 'describe-queue', params: { id: recording.match_id }, query: { video_id: String(recording.video_id) } }" />
      </div>
      <p v-if="!recording.clips.length" class="muted q-mt-sm q-mb-none">Brak znaczników.</p>
      <q-list v-else separator class="q-mt-sm">
        <q-item v-for="clip in recording.clips" :key="clip.id" :class="{ 'row-highlighted': clip.id === highlighted }">
          <q-item-section>
            <q-item-label class="marker-title"><span class="info-time">{{ clip.clock }}</span><strong>{{ clip.category || 'Znacznik' }}</strong></q-item-label>
            <q-item-label caption class="info-context">
              {{ clip.period && clip.period_clock ? `${clip.period} · ${clip.period_clock} od początku kwarty` : 'Kwarta nieustalona' }}
              <span v-if="clip.official" class="info-person"> · {{ clip.official }}</span>
            </q-item-label>
            <div class="row q-gutter-xs q-mt-xs">
              <q-badge class="state-badge" :data-status="clip.status" :label="cutStatus[clip.status]" :title="clip.error ?? undefined" />
              <q-badge class="state-badge" :data-status="clip.described ? undefined : 'queued'" :label="clip.described ? 'Opisany' : 'Do opisania'" />
            </div>
            <div class="row q-gutter-xs q-mt-xs">
              <q-btn v-if="recording.playable" flat dense label="Przewiń" :disable="locked" @click="$emit('seek', clip.time_sec)" />
              <q-btn flat dense color="primary" label="Otwórz klip" :to="{ name: 'clip-detail', params: { id: clip.id } }" />
              <q-btn v-if="clip.can_delete" flat dense icon="delete_outline" color="negative"
                :aria-label="`Usuń znacznik ${clip.clock}`" :disable="busy" @click="$emit('deleteClip', clip)" />
            </div>
          </q-item-section>
        </q-item>
      </q-list>
    </q-card-section>
  </q-card>
</template>

<style scoped>
.marker-title { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 8px; }
.period-section { scroll-margin-top: 90px; }
.period-list { padding: 0; margin-bottom: 0; list-style: none; }
.period-list li {
  display: grid;
  grid-template-columns: minmax(2rem, auto) minmax(2.7rem, auto) minmax(0, 1fr) auto;
  align-items: center;
  justify-items: start;
  gap: 4px;
  min-height: 42px;
}
.period-list li + li { border-top: 1px solid var(--surface-border); }
.next-period strong { color: var(--q-primary); }

@media (pointer: coarse) {
  .period-list .q-btn { min-width: 44px; min-height: 44px; }
}
</style>
