<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import MediaPlayer from '../common/MediaPlayer.vue'

type Point = { id: string; time: number; label: string; period?: boolean }
const props = defineProps<{
  id: number; name: string; start: number; fps: number; canClip: boolean; canMark: boolean;
  busy: boolean; locked?: boolean; points: Point[]; rangeStart: number | null; rangeEnd: number | null
}>()
const emit = defineEmits<{
  marker: [time: number]; failed: []; undo: []; quick: []; quarter: [];
  rangeStart: []; rangeEnd: [];
}>()
const player = ref<InstanceType<typeof MediaPlayer>>()
const studio = ref<HTMLElement>()
const time = ref(0)
const duration = ref(0)
const rates = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2]
const help = ref(false)
const rate = ref(1)

const element = () => player.value?.element()
const currentTime = () => player.value?.currentTime() ?? 0
function seek(seconds: number) {
  if (!props.locked) player.value?.seek(seconds)
}

function stepFrame(direction: number) {
  if (props.locked || !duration.value) return
  element()?.pause()
  seek(currentTime() + direction / props.fps)
}

function setRate(value: number) {
  const video = element()
  if (video && !props.locked) video.playbackRate = rate.value = value
}

function clock(seconds: number) {
  const hundredths = Math.round(seconds * 100)
  return `${Math.floor(hundredths / 6000)}:${(hundredths % 6000 / 100).toFixed(2).padStart(5, '0')}`
}

function percent(seconds: number) {
  return `${Math.max(0, Math.min(100, 100 * seconds / duration.value))}%`
}

function fullscreen() {
  if (document.fullscreenElement) void document.exitFullscreen()
  else void studio.value?.requestFullscreen?.().catch(() => {})
}

function keyboard(event: KeyboardEvent) {
  const target = event.composedPath()[0]
  if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey
    || (target instanceof HTMLElement && target.closest('input, textarea, select, [contenteditable], [role="combobox"], [role="slider"]'))) return
  const key = event.key.toLowerCase()
  if (target instanceof HTMLElement && target.closest('button, a, [role="button"]')
    && !['z', 'm', 'q', 'i', 'o', 'backspace'].includes(key)) return
  if (key === '?') { help.value = !help.value }
  else if (key === 'escape' && help.value) help.value = false
  else if (key === 'f' && !event.repeat) fullscreen()
  else if (key === 'z' && props.canClip && !props.busy && !event.repeat && duration.value) emit('marker', currentTime())
  else if (key === 'm' && props.canClip && !props.busy && !event.repeat && duration.value) emit('quick')
  else if (key === 'backspace' && props.canClip && !props.busy && !event.repeat) emit('undo')
  else if (key === 'q' && props.canMark && !props.busy && !event.repeat && duration.value) emit('quarter')
  else if (!props.locked && duration.value) {
    if (key === ' ' && !event.repeat) player.value?.togglePlayback()
    else if (key === 'arrowleft' || key === 'arrowright') seek(currentTime() + (key === 'arrowleft' ? -1 : 1) * (event.shiftKey ? 5 : 1))
    else if (key === ',' || key === '.') stepFrame(key === ',' ? -1 : 1)
    else if (key === '[' || key === ']') {
      const index = rates.indexOf(rate.value)
      setRate(rates[Math.max(0, Math.min(rates.length - 1, index + (key === '[' ? -1 : 1)))] ?? 1)
    } else if (props.canClip && !props.busy && !event.repeat) {
      if (key === 'i') emit('rangeStart')
      else if (key === 'o') emit('rangeEnd')
      else return
    } else return
  } else return
  event.preventDefault()
  event.stopPropagation()
}

onMounted(() => window.addEventListener('keydown', keyboard, true))
onUnmounted(() => window.removeEventListener('keydown', keyboard, true))
defineExpose({ seek, currentTime, element, preview: (start: number, end: number) => player.value?.preview(start, end) })
</script>

<template>
  <section ref="studio" class="recording-studio">
    <MediaPlayer ref="player" :src="`/videos/${id}/stream`" :label="name" :start="start" :locked="locked"
      @ready="duration = $event" @time="time = $event" @rate="rate = $event" @failed="$emit('failed')" />
    <p v-if="locked" class="sync-label" role="status">Odtwarzanie zsynchronizowane z prowadzącym</p>
    <div v-if="duration" class="timeline" aria-label="Oś czasu nagrania">
      <span v-if="rangeStart !== null && rangeEnd !== null && rangeEnd > rangeStart" class="range-selection"
        :style="{ left: percent(rangeStart), width: percent(rangeEnd - rangeStart) }" />
      <span class="timeline-playhead" :style="{ left: percent(time) }" />
      <input class="timeline-seek" type="range" :value="time" min="0" :max="duration" step="any"
        aria-label="Pozycja na osi znaczników" :aria-valuetext="clock(time)" :disabled="locked"
        @input="seek(Number(($event.target as HTMLInputElement).value))" />
      <button v-for="point in points.filter(point => point.time <= duration)" :key="point.id" type="button"
        class="timeline-point" :class="{ 'timeline-period': point.period }"
        :style="{ left: percent(point.time) }" :title="point.label" :aria-label="point.label"
        :disabled="locked" @click="seek(point.time)" />
    </div>
    <section class="timeline-key" :aria-labelledby="`timeline-legend-${id}`">
      <h2 :id="`timeline-legend-${id}`" class="timeline-key-title">Legenda osi czasu</h2>
      <ul class="timeline-legend">
        <li><span class="legend-swatch legend-period" aria-hidden="true" />Początek kwarty</li>
        <li><span class="legend-swatch legend-clip" aria-hidden="true" />Znacznik klipu</li>
        <li><span class="legend-swatch legend-range" aria-hidden="true" />Zakres cięcia</li>
        <li><span class="legend-swatch legend-position" aria-hidden="true" />Aktualna pozycja</li>
      </ul>
    </section>
    <div class="studio-toolbar row items-center q-gutter-xs">
      <strong class="studio-clock">{{ clock(time) }} / {{ clock(duration) }}</strong>
      <q-space />
      <q-btn flat dense icon="skip_previous" aria-label="Klatka wstecz (,)" :disable="locked || !duration" @click="stepFrame(-1)" />
      <q-btn flat dense icon="skip_next" aria-label="Klatka naprzód (.)" :disable="locked || !duration" @click="stepFrame(1)" />
      <q-select v-model="rate" :options="rates" :display-value="`${rate}×`" aria-label="Prędkość odtwarzania"
        borderless dense dark :disable="locked || !duration" @update:model-value="setRate" />
      <q-btn flat dense icon="fullscreen" aria-label="Pełny ekran analizy (F)" @click="fullscreen" />
      <q-btn flat dense icon="keyboard" aria-label="Skróty klawiszowe" :aria-expanded="help" @click="help = !help" />
    </div>
    <p v-if="help" class="q-ma-sm shortcut-help">
      Spacja odtwarzanie · ← / → ±1 s · Shift + ← / → ±5 s · , / . klatka · [ / ] tempo ·
      Z szybkie cięcie · Backspace cofnij · M znacznik z notatką · Q początek kwarty · I / O ręczne granice · F pełny ekran
    </p>
    <slot :ready="Boolean(duration)" />
  </section>
</template>

<style scoped>
.recording-studio {
  --quarter-color: #b3cce1;
  --clip-color: var(--brand-orange);
  --range-color: var(--player-range);
  --position-color: var(--brand-cream);
  padding: 8px;
  border-radius: var(--radius-surface);
  background: var(--player-bg);
  color: var(--brand-cream);
}
.recording-studio:fullscreen {
  overflow: auto;
  padding: 12px;
}
.studio-toolbar { padding: 0 6px 2px; }
.studio-clock { font-variant-numeric: tabular-nums; font-size: 0.85rem; }
.shortcut-help, .sync-label { color: var(--player-muted); }
.sync-label { margin: 4px 6px; font-size: 0.8rem; }
.timeline { position: relative; height: 22px; margin: 5px 12px; background: var(--player-track); border-radius: 4px; }
.timeline:focus-within { outline: 2px solid #fff; outline-offset: 2px; }
.timeline-seek { position: absolute; inset: 0; width: 100%; height: 100%; margin: 0; opacity: 0; cursor: pointer; }
.range-selection { position: absolute; inset-block: 0; }
.timeline-playhead { position: absolute; inset-block: 0; pointer-events: none; }
.timeline-point {
  position: absolute; top: 4px; width: 14px; height: 14px; padding: 0; transform: translateX(-50%);
  cursor: pointer;
}
.timeline-point[disabled] { cursor: default; }
.timeline-period { top: 0; height: 22px; }
.timeline-point:focus-visible { outline: 2px solid #fff; outline-offset: 2px; }
.timeline-point, .legend-clip { border: 2px solid #f5eee2; border-radius: 50%; background: var(--clip-color); }
.timeline-period, .legend-period { border-radius: 3px; background: var(--quarter-color); }
.range-selection, .legend-range { background: var(--range-color); }
.timeline-playhead, .legend-position { width: 2px; background: var(--position-color); }
.timeline-key {
  margin: 8px 12px 4px;
  padding: 8px 10px;
  border: 1px solid var(--player-border);
  border-radius: var(--radius-small);
  background: var(--player-surface);
}
.timeline-key-title {
  margin: 0 0 4px;
  font-size: 0.875rem;
  font-weight: 700;
  line-height: 1.4;
}
.timeline-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  padding: 0;
  margin: 0;
  list-style: none;
  color: var(--player-muted);
  font-size: 0.75rem;
}
.timeline-legend li { display: inline-flex; align-items: center; gap: 6px; }
.legend-swatch { display: inline-block; height: 12px; }
.legend-period { width: 8px; }
.legend-clip { width: 12px; }
.legend-range { width: 18px; border: 1px solid var(--quarter-color); border-radius: 2px; }

@media (pointer: coarse) {
  .studio-toolbar .q-btn { min-width: 44px; min-height: 44px; }
}

@media (max-width: 420px) {
  .studio-toolbar { justify-content: space-between; }
  .studio-toolbar .q-space { display: none; }
  .studio-clock { flex: 1 0 100%; margin-bottom: 2px; }
}
</style>
