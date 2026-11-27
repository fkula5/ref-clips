<script setup lang="ts">
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import { nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, errorMessage } from '../api/client'
import { fetchClip } from '../api/clips'
import ClipFeedback from '../components/clips/ClipFeedback.vue'
import ClipPlayer from '../components/clips/ClipPlayer.vue'
import ClipDescriptionForm from '../components/clips/ClipDescriptionForm.vue'
import ClipSharing from '../components/clips/ClipSharing.vue'
import ClipSetPicker from '../components/clips/ClipSetPicker.vue'
import ClipAdjust from '../components/clips/ClipAdjust.vue'
import ConfirmAction from '../components/common/ConfirmAction.vue'
import { useSession } from '../composables/useSession'
import type { ClipDetail } from '../types/api'

const route = useRoute()
const router = useRouter()
const session = useSession()
const clip = ref<ClipDetail | null>(null)
const loading = ref(true)
const error = ref('')
const refresh = ref(0)
const editing = ref(false)
const confirmDelete = ref(false)
const savingAction = ref(false)
const actionError = ref('')

watch(() => route.params.id, () => {
  editing.value = false
  confirmDelete.value = false
  actionError.value = ''
})

watch([clip, () => route.hash], async ([detail, hash]) => {
  if (detail && (hash === '#oceny' || hash === '#komentarze')) {
    await nextTick()
    document.getElementById(hash.slice(1))?.scrollIntoView()
  }
}, { once: false })

async function clipAction(action: 'recut' | 'delete') {
  const current = clip.value
  if (!current || savingAction.value) return
  savingAction.value = true
  actionError.value = ''
  try {
    await session.submit(`/clips/${current.id}/${action}`)
    if (String(current.id) !== route.params.id) return
    if (action === 'delete') {
      confirmDelete.value = false
      await router.replace({ name: 'match-detail', params: { id: current.match.id } })
    } else {
      refresh.value++
    }
  } catch (err) {
    actionError.value = errorMessage(err)
    confirmDelete.value = false
  } finally {
    savingAction.value = false
  }
}

watch([() => route.params.id, () => route.query, refresh], async ([id, query], _, onCleanup) => {
  if (typeof id !== 'string') return
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  if (String(clip.value?.id) !== id) clip.value = null
  loading.value = true
  error.value = ''

  try {
    const filters = new URLSearchParams()
    for (const key of ['person', 'category_id', 'period', 'described', 'rating', 'group', 'since', 'video_id']) {
      const value = query[key]
      if (typeof value === 'string') filters.set(key, value)
    }
    const detail = await fetchClip(id, controller.signal, filters)
    if (!controller.signal.aborted) clip.value = detail
  } catch (err) {
    if (controller.signal.aborted) return
    if (err instanceof ApiError && err.status === 401) {
      session.clear()
      await router.replace({ name: 'login', query: { next: route.fullPath } })
    } else {
      error.value = errorMessage(err)
      if (err instanceof ApiError && err.status === 404) clip.value = null
    }
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })

watch(() => clip.value?.pending, (pending, _, onCleanup) => {
  if (!pending) return
  const timer = setInterval(() => {
    if (!document.hidden && !loading.value && !editing.value && !error.value
        && !document.activeElement?.closest('form')) refresh.value++
  }, 5000)
  onCleanup(() => clearInterval(timer))
})
</script>

<template>
  <q-page class="matches-page">
    <q-btn
      flat dense color="primary" icon="arrow_back" :label="clip ? 'Wróć do meczu' : 'Mecze'" class="q-mb-lg"
      :to="clip ? { name: 'match-detail', params: { id: clip.match.id } } : { name: 'matches' }"
    />
    <LoadingSkeleton v-if="loading && !clip" variant="media" label="Ładowanie klipu" />
    <q-banner v-if="error" class="error-banner q-mb-md" role="alert">
      {{ error }}
      <template #action><q-btn flat label="Ponów" @click="refresh++" /></template>
    </q-banner>
    <template v-if="clip">
      <header class="page-heading q-mt-md">
        <div>
          <p class="muted">{{ clip.match.title }}</p>
          <h1>Klip <span class="clip-heading-time">{{ clip.time }}</span></h1>
          <q-badge class="state-badge" :data-status="clip.status_key" :label="clip.status" />
        </div>
        <div class="row items-center q-gutter-sm">
          <q-btn flat round icon="refresh" aria-label="Odśwież klip" :disable="loading" @click="refresh++" />
          <q-btn outline color="primary" label="Pełny widok klipu" :href="`/clips/${clip.id}?view=classic`" />
          <q-btn v-if="clip.can_delete" flat color="negative" label="Usuń klip" :disable="savingAction" @click="confirmDelete = true" />
        </div>
      </header>
      <nav class="row q-gutter-sm q-mb-md" aria-label="Klipy w meczu">
        <q-btn v-if="clip.previous" outline color="primary" :label="`Poprzedni klip · ${clip.previous.time}`" :to="{ name: 'clip-detail', params: { id: clip.previous.id }, query: route.query }" />
        <q-btn v-if="clip.next" outline color="primary" :label="`Następny klip · ${clip.next.time}`" :to="{ name: 'clip-detail', params: { id: clip.next.id }, query: route.query }" />
      </nav>
      <q-banner v-if="actionError || clip.cut_error" class="error-banner q-mb-md" role="alert">
        {{ actionError || clip.cut_error }}
        <template v-if="clip.can_recut" #action>
          <q-btn flat label="Wytnij ponownie" :loading="savingAction" @click="clipAction('recut')" />
        </template>
      </q-banner>
      <ClipPlayer :key="clip.stream_url ?? clip.id" :clip="clip" />
      <ClipAdjust v-if="clip.adjust" :key="`adjust-${clip.id}`" :id="clip.id" :range="clip.adjust" @saved="refresh++" />
      <q-card flat bordered class="q-my-lg">
        <q-card-section>
          <h2 class="text-h6 q-mb-sm">Opis akcji</h2>
          <dl class="clip-facts">
            <div><dt>Kwarta</dt><dd><span class="info-time">{{ clip.period }}</span></dd></div>
            <div v-if="clip.official"><dt>Sędzia</dt><dd class="info-person">{{ clip.official }}</dd></div>
            <div v-if="clip.category"><dt>Kategoria</dt><dd><span class="info-category">{{ clip.category }}</span></dd></div>
          </dl>
          <p v-if="clip.description" class="clip-description info-copy q-mb-none">{{ clip.description }}</p>
          <p v-else class="muted q-mb-none">{{ clip.described ? 'Brak opisu.' : 'Znacznik do opisania.' }}</p>
        </q-card-section>
        <q-card-actions v-if="clip.editor">
          <q-btn flat color="primary" :label="editing ? 'Zamknij edycję' : 'Edytuj opis'" :aria-expanded="editing" @click="editing = !editing" />
        </q-card-actions>
        <q-card-section v-if="clip.editor && editing">
          <ClipDescriptionForm :key="clip.id" :id="clip.id" :editor="clip.editor" @saved="editing = false; refresh++" />
        </q-card-section>
      </q-card>
      <ClipFeedback :key="clip.id" :clip="clip" @saved="refresh++" />
      <ClipSharing v-if="clip.sharing" :key="`share-${clip.id}`" :id="clip.id" :sharing="clip.sharing" @saved="refresh++" />
      <ClipSetPicker v-if="clip.set_choices" :key="`set-${clip.id}`" :id="clip.id" :choices="clip.set_choices" @saved="refresh++" />
      <ConfirmAction v-model="confirmDelete" title="Usunąć klip?" message="Usunięcie klipu razem z jego ocenami i komentarzami jest trwałe." label="Usuń klip" :busy="savingAction" @confirm="clipAction('delete')" />
    </template>
  </q-page>
</template>

<style scoped>
.clip-heading-time { color: var(--text-time); font-variant-numeric: tabular-nums; }
.clip-facts { display: flex; flex-wrap: wrap; gap: 8px 24px; margin: 0 0 12px; }
.clip-facts dt { font-size: 0.8rem; color: var(--text-muted); }
.clip-facts dd { margin: 2px 0 0; }
.clip-description {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
