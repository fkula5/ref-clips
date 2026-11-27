<script setup lang="ts">
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, errorMessage } from '../api/client'
import { fetchMatchDetail } from '../api/matches'
import MatchClips from '../components/matches/MatchClips.vue'
import MatchRecordings from '../components/matches/MatchRecordings.vue'
import MatchUpload from '../components/matches/MatchUpload.vue'
import MatchDocuments from '../components/matches/MatchDocuments.vue'
import CommentsPanel from '../components/common/CommentsPanel.vue'
import ConfirmAction from '../components/common/ConfirmAction.vue'
import { useSession } from '../composables/useSession'
import type { MatchDetail } from '../types/api'

const route = useRoute()
const router = useRouter()
const session = useSession()
const match = ref<MatchDetail | null>(null)
const loading = ref(true)
const error = ref('')
const refresh = ref(0)
const confirmDelete = ref(false)
const deleting = ref(false)
const dateFormatter = new Intl.DateTimeFormat('pl-PL', { dateStyle: 'long' })

async function deleteMatch() {
  const id = match.value?.id
  if (!id || deleting.value) return
  deleting.value = true
  error.value = ''
  try {
    await session.submit(`/matches/${id}/delete`)
    await router.replace({ name: 'matches' })
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    confirmDelete.value = false
    deleting.value = false
  }
}

watch([() => route.params.id, () => route.query.page, refresh], async ([id, page], _, onCleanup) => {
  if (typeof id !== 'string') return
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  if (String(match.value?.id) !== id) match.value = null
  loading.value = true
  error.value = ''
  try {
    const detail = await fetchMatchDetail(id, typeof page === 'string' ? page : '1', controller.signal)
    if (!controller.signal.aborted) match.value = detail
  } catch (err) {
    if (controller.signal.aborted) return
    if (err instanceof ApiError && err.status === 401) {
      session.clear()
      await router.replace({ name: 'login', query: { next: route.fullPath } })
    } else {
      error.value = errorMessage(err)
    }
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })

watch(() => match.value?.pending, (pending, _, onCleanup) => {
  if (!pending) return
  const timer = setInterval(() => {
    if (!document.hidden && !loading.value && !error.value && !deleting.value) refresh.value++
  }, 5000)
  onCleanup(() => clearInterval(timer))
})

function changePage(page: number) {
  return router.push({ query: { ...route.query, page: page > 1 ? String(page) : undefined } })
}
</script>

<template>
  <q-page class="matches-page">
    <q-btn flat dense color="primary" icon="arrow_back" label="Mecze" :to="{ name: 'matches' }" class="q-mb-lg" />
    <LoadingSkeleton v-if="loading && !match" variant="detail" label="Ładowanie szczegółów meczu" />
    <q-banner v-if="error" class="error-banner q-mb-md" role="alert">
      {{ error }}
      <template #action><q-btn flat label="Ponów" @click="refresh++" /></template>
    </q-banner>
    <template v-if="match">
      <header class="page-heading q-mt-md">
        <div>
          <p class="muted">{{ dateFormatter.format(new Date(match.date + 'T12:00:00')) }} · {{ match.level || 'Bez ligi' }}</p>
          <h1>{{ match.teams }}</h1>
          <q-badge class="state-badge" :data-status="match.state.code" :label="match.state.label" />
          <p v-if="match.state.detail" class="muted q-mt-sm">{{ match.state.detail }}</p>
          <p v-if="match.expiry" class="muted q-mt-sm">{{ match.expiry }}</p>
        </div>
        <div class="row q-gutter-sm">
          <q-btn v-if="match.can_edit" outline color="primary" label="Edytuj" :to="{ name: 'match-edit', params: { id: match.id } }" />
          <q-btn v-if="match.can_delete" flat color="negative" label="Usuń mecz" :disable="deleting" @click="confirmDelete = true" />
          <q-btn flat color="primary" label="Pełny widok meczu" :href="`/matches/${match.id}?view=classic`" />
        </div>
      </header>
      <q-card flat bordered class="q-mb-lg">
        <q-card-section>
          <h2 class="text-h6 q-mb-sm">Obsada sędziowska</h2>
          <div v-if="match.officials.length" class="row q-gutter-sm">
            <q-chip v-for="official in match.officials" :key="official.function" class="crew-chip">
              <strong class="q-mr-sm">{{ official.function }}</strong>
              <RouterLink v-if="official.user_id" :to="{ name: 'referee', params: { id: official.user_id } }">{{ official.name }}</RouterLink>
              <span v-else>{{ official.name }}</span>
            </q-chip>
          </div>
          <p v-else class="muted q-mb-none">Nie podano obsady.</p>
        </q-card-section>
        <q-separator />
        <q-card-section>
          <MatchRecordings :key="match.id" :recordings="match.videos" @saved="refresh++" />
          <MatchUpload v-if="match.upload" :key="`upload-${match.id}`" :id="match.id" :settings="match.upload" @uploaded="refresh++" />
          <q-btn flat round icon="refresh" aria-label="Odśwież nagrania i klipy" class="q-mt-sm" :disable="loading" @click="refresh++" />
        </q-card-section>
        <q-separator />
        <q-card-section>
          <q-btn v-if="match.can_describe && match.clips.total" outline color="primary" label="Opisz znaczniki" :to="{ name: 'describe-queue', params: { id: match.id } }" />
          <q-btn v-if="match.clips.total" flat color="primary" label="Filtruj klipy meczu" :to="{ name: 'clips', query: { match_id: String(match.id) } }" />
          <MatchClips :clips="match.clips" :loading="loading" @change-page="changePage" />
        </q-card-section>
      </q-card>
      <ConfirmAction v-model="confirmDelete" title="Usunąć mecz?" message="Usunięcie meczu oraz jego nagrań, klipów i opinii jest trwałe." label="Usuń mecz" :busy="deleting" @confirm="deleteMatch" />
      <MatchDocuments :key="`documents-${match.id}`" :id="match.id" :documents="match.documents" @saved="refresh++" />
      <q-card flat bordered>
        <q-card-section><CommentsPanel :key="`comments-${match.id}`" :base="`/matches/${match.id}`" /></q-card-section>
      </q-card>
    </template>
  </q-page>
</template>
