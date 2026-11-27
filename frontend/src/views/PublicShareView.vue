<script setup lang="ts">
import MediaPlayer from '../components/common/MediaPlayer.vue'
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { errorMessage, request } from '../api/client'

interface PublicClips { single: boolean; clips: { position: number; level: string; category: string; filename: string }[] }
const route = useRoute()
const path = computed(() => `/s/${encodeURIComponent(String(route.params.code))}`)
const data = ref<PublicClips>()
const error = ref('')
const loading = ref(false)

watch(path, async (url, _, onCleanup) => {
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  data.value = undefined
  error.value = ''
  loading.value = true
  try {
    const result = await request<PublicClips>(url, { credentials: 'omit', signal: controller.signal })
    if (!controller.signal.aborted) data.value = result
  } catch (err) {
    if (!controller.signal.aborted) error.value = errorMessage(err)
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })
</script>

<template>
  <main class="shared-clips">
    <h1 class="text-h4">{{ data?.single ? 'Udostępniony klip' : 'Udostępnione klipy' }}</h1>
    <LoadingSkeleton v-if="loading && !data" variant="media" label="Ładowanie udostępnionych klipów" />
    <q-banner v-if="error" class="error-banner" role="alert">{{ error }}</q-banner>
    <template v-if="data">
      <q-card v-for="clip in data.clips" :key="clip.position" flat bordered class="q-mb-lg">
        <q-card-section>
          <h2 class="text-h6">{{ clip.category || `Klip ${clip.position}` }}</h2>
          <p v-if="clip.level">{{ clip.level }}</p>
          <MediaPlayer :src="`${path}/clips/${clip.position}/file`" :label="clip.category || `Klip ${clip.position}`" />
          <q-btn v-if="data.single" color="primary" class="q-mt-md" label="Pobierz MP4" :href="`${path}/clips/${clip.position}/download`" />
        </q-card-section>
      </q-card>
      <q-btn v-if="!data.single" color="primary" label="Pobierz klipy jako ZIP" :href="`${path}/zip`" />
    </template>
  </main>
</template>

<style scoped>
.shared-clips { max-width: 1000px; margin: 0 auto; padding: 32px 20px; }
</style>
