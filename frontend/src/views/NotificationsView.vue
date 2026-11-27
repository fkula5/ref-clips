<script setup lang="ts">
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, errorMessage } from '../api/client'
import { fetchNotifications } from '../api/notifications'
import type { NotificationPage } from '../api/notifications'
import { useSession } from '../composables/useSession'

const route = useRoute()
const router = useRouter()
const session = useSession()
const page = ref<NotificationPage>()
const error = ref('')
const loading = ref(false)
const busy = ref(false)
const refresh = ref(0)

async function fail(err: unknown) {
  if (err instanceof ApiError && err.status === 401) {
    session.clear()
    await router.replace({ name: 'login', query: { next: route.fullPath } })
  } else {
    error.value = errorMessage(err)
  }
}

watch([() => route.query.page, refresh], async ([current], _, onCleanup) => {
  if (route.name !== 'notifications') return
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  loading.value = true
  error.value = ''
  try {
    const data = await fetchNotifications(typeof current === 'string' ? current : '1', controller.signal)
    if (!controller.signal.aborted) page.value = data
  } catch (err) {
    if (!controller.signal.aborted) await fail(err)
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })

async function change(path: string, open = false) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    if (open) {
      const { target } = await session.submit<{ target: string }>(path)
      const clip = target.match(/^\/clips\/(\d+)(?:#(oceny|komentarze))?$/)
      if (clip) {
        await router.push({ name: 'clip-detail', params: { id: clip[1] }, hash: clip[2] ? `#${clip[2]}` : '' })
      } else if (/^\/matches\/\d+#komentarze$/.test(target)) {
        const id = target.split('/')[2].split('#')[0]
        await router.push({ name: 'match-detail', params: { id }, hash: '#komentarze' })
      } else if (target === '/groups') {
        await router.push({ name: 'groups' })
      } else if (/^\/self-assessments\/\d+$/.test(target)) {
        await router.push({ name: 'self-assessment', params: { id: target.split('/')[2] } })
      } else if (/^\/sheets\/\d+$/.test(target)) {
        await router.push({ name: 'sheet', params: { id: target.split('/')[2] } })
      } else if (target.startsWith('/') && !target.startsWith('//')) {
        location.assign(target)
      }
    } else {
      await session.submit(path)
      refresh.value++
    }
  } catch (err) {
    await fail(err)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <q-page class="matches-page">
    <header class="page-heading">
      <h1>Powiadomienia</h1>
      <q-btn flat color="primary" label="Ustawienia" :to="{ name: 'notification-settings' }" />
    </header>
    <LoadingSkeleton v-if="loading && !page" variant="list" label="Ładowanie powiadomień" />
    <q-linear-progress v-else-if="loading" indeterminate color="primary" aria-label="Odświeżanie danych" />
    <q-banner v-if="error" class="error-banner q-mb-md" role="alert">
      {{ error }}
      <template #action><q-btn flat label="Ponów" @click="refresh++" /></template>
    </q-banner>
    <template v-if="page">
      <q-btn v-if="page.unread" outline color="primary" label="Oznacz wszystkie jako przeczytane" class="q-mb-md" :disable="busy" @click="change('/notifications/read-all')" />
      <p v-if="!page.items.length" class="muted">Brak powiadomień.</p>
      <q-list v-else bordered separator class="surface-panel rounded-borders">
        <q-item v-for="item in page.items" :key="item.id" :class="{ 'row-highlighted': item.unread }">
          <q-item-section>
            <q-item-label>{{ item.actor }} · {{ item.kind }}</q-item-label>
            <q-item-label caption>{{ [item.context, item.verdict, item.date].filter(Boolean).join(' · ') }}</q-item-label>
            <div class="row q-mt-xs">
              <q-btn flat dense color="primary" label="Otwórz" :disable="busy" @click="change(`/notifications/${item.id}/open`, true)" />
              <q-btn v-if="item.unread" flat dense label="Oznacz jako przeczytane" :disable="busy" @click="change(`/notifications/${item.id}/read`)" />
            </div>
          </q-item-section>
        </q-item>
      </q-list>
      <q-pagination v-if="page.pages > 1" :model-value="page.page" :max="page.pages" :max-pages="5" boundary-numbers class="q-mt-lg" @update:model-value="number => router.push({ query: { page: number > 1 ? String(number) : undefined } })" />
    </template>
  </q-page>
</template>
