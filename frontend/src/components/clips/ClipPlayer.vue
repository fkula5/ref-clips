<script setup lang="ts">
import { ref } from 'vue'
import type { ClipDetail } from '../../types/api'
import MediaPlayer from '../common/MediaPlayer.vue'

defineProps<{ clip: ClipDetail }>()
const failed = ref(false)
</script>

<template>
  <section aria-label="Odtwarzacz klipu">
    <MediaPlayer
      v-if="clip.stream_url && !failed"
      :src="clip.stream_url"
      :label="`Klip z czasu ${clip.time}`"
      @failed="failed = true"
    />
    <q-banner v-else-if="failed || clip.unavailable" class="error-banner" role="alert">
      Plik klipu jest niedostępny.
    </q-banner>
    <div class="row items-center q-gutter-sm q-mt-sm">
      <q-btn v-if="clip.stream_url" flat color="primary" icon="download" label="Pobierz MP4" :href="`/clips/${clip.id}/download`" />
      <q-btn v-if="clip.recording_url" flat color="primary" label="Pokaż w pełnym nagraniu" :to="clip.recording_url.replace('/videos/', '/recordings/')" />
    </div>
  </section>
</template>

