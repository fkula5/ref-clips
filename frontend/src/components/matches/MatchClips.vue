<script setup lang="ts">
import type { MatchDetail } from '../../types/api'
import ClipListSummary from '../clips/ClipListSummary.vue'

defineProps<{ clips: MatchDetail['clips']; loading: boolean }>()
defineEmits<{ changePage: [page: number] }>()
</script>

<template>
  <section id="klipy" aria-labelledby="clips-title" :aria-busy="loading">
    <h2 id="clips-title" class="text-h6 q-mb-md">Klipy ({{ clips.total }})</h2>
    <p v-if="!clips.total" class="muted">Ten mecz nie ma jeszcze klipów.</p>
    <q-list v-else bordered separator class="rounded-borders">
      <q-item v-for="clip in clips.items" :key="clip.id" clickable :to="{ name: 'clip-detail', params: { id: clip.id } }">
        <q-item-section>
          <ClipListSummary :time="clip.time" :description="clip.description"
            :title="clip.category || (clip.described ? 'Klip' : 'Znacznik do opisania')" />
        </q-item-section>
        <q-item-section side><q-badge class="state-badge" :data-status="clip.status_key" :label="clip.status" /></q-item-section>
      </q-item>
    </q-list>
    <q-pagination
      v-if="clips.pages > 1"
      class="q-mt-md"
      :model-value="clips.page"
      :max="clips.pages"
      :max-pages="5"
      :disable="loading"
      boundary-numbers
      @update:model-value="$emit('changePage', $event)"
    />
  </section>
</template>
