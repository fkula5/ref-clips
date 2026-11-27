<script setup lang="ts">
import { ref, watch } from 'vue'
import '@videojs/html/video/player'
import '@videojs/html/video/neutral-skin'
import '@videojs/html/i18n/locales/pl/register'

const props = withDefaults(defineProps<{
  src: string
  label: string
  start?: number
  locked?: boolean
}>(), { start: 0 })
const emit = defineEmits<{ failed: []; time: [seconds: number]; ready: [duration: number]; rate: [speed: number] }>()
const video = ref<HTMLVideoElement>()
let previewEnd: number | null = null
watch(() => props.locked, locked => { if (locked) previewEnd = null })

function seek(seconds: number) {
  const element = video.value
  if (element && Number.isFinite(seconds) && Number.isFinite(element.duration)) {
    element.currentTime = Math.max(0, Math.min(seconds, element.duration))
    emit('time', element.currentTime)
  }
}

function loaded() {
  seek(props.start)
  if (video.value && Number.isFinite(video.value.duration)) emit('ready', video.value.duration)
}

function togglePlayback() {
  const element = video.value
  if (!element || props.locked) return
  if (element.paused) void element.play().catch(() => emit('failed'))
  else element.pause()
}

function preview(start: number, end: number) {
  if (!video.value || props.locked || end <= start) return
  seek(start)
  previewEnd = end
  void video.value.play().catch(() => { previewEnd = null })
}

function timeChanged() {
  const element = video.value
  if (!element) return
  if (previewEnd !== null && element.currentTime >= previewEnd) {
    const end = previewEnd
    previewEnd = null
    element.pause()
    seek(end)
  }
  emit('time', element.currentTime)
}

defineExpose({ element: () => video.value, seek, preview, togglePlayback, currentTime: () => video.value?.currentTime ?? 0 })
</script>

<template>
  <video-player class="media-player" lang="pl">
    <video-neutral-skin :inert="locked" :class="{ 'media-locked': locked }">
      <video
        ref="video" :src="src" :aria-label="label" playsinline preload="metadata"
        @loadedmetadata="loaded" @timeupdate="timeChanged" @pause="previewEnd = null" @error="$emit('failed')"
        @ratechange="video && $emit('rate', video.playbackRate)"
      />
    </video-neutral-skin>
  </video-player>
</template>

<style scoped>
.media-player,
video-neutral-skin {
  display: block;
  width: 100%;
}

video-neutral-skin {
  aspect-ratio: 16 / 9;
  max-height: 67vh;
  background: var(--player-frame);
  border-radius: var(--radius-control);
  overflow: hidden;
}

video-neutral-skin:not(:defined) {
  visibility: hidden;
}

.media-locked {
  pointer-events: none;
}

video {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
</style>
