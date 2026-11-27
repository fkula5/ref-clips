<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { Upload, DetailedError } from 'tus-js-client'
import { ApiError, errorMessage, request } from '../../api/client'
import { useSession } from '../../composables/useSession'
import type { MatchDetail } from '../../types/api'
import ConfirmAction from '../common/ConfirmAction.vue'

const props = defineProps<{ id: number; settings: NonNullable<MatchDetail['upload']> }>()
const emit = defineEmits<{ uploaded: [] }>()
const { csrfHeaders, user } = useSession()
const files = ref<File[] | null>(null)
const file = computed(() => files.value?.[0])
const label = ref('')
const periods = ref<string[]>([])
const notes = ref('')
const uploading = ref(false)
const progress = ref(0)
const error = ref('')
const status = ref('')
const unfinished = ref('')
const cancelling = ref(false)
const confirmation = ref(false)
let active: Upload | undefined
let attempt = 0

async function start() {
  const selected = file.value
  if (!selected || uploading.value) return
  error.value = ''
  status.value = ''
  unfinished.value = ''
  if (!selected.size || selected.size > props.settings.max_bytes) {
    error.value = 'Rozmiar pliku przekracza limit albo plik jest pusty.'
    return
  }
  const current = ++attempt
  uploading.value = true
  progress.value = 0
  const content = props.settings.periods.filter(period => periods.value.includes(period)).join(',') || 'full'
  const text = notes.value.trimEnd()
  const fingerprint = JSON.stringify([user.value?.id, props.id, selected.name, selected.size, selected.lastModified, content, label.value.trim()])
  let notesSavedFor = ''

  try {
    const headers = await csrfHeaders()
    if (attempt !== current) return
    const upload = new Upload(selected, {
      endpoint: '/uploads/',
      chunkSize: props.settings.chunk_bytes,
      headers,
      retryDelays: [0, 1000, 3000, 5000, 10000, 20000, 30000],
      storeFingerprintForResuming: true,
      removeFingerprintOnSuccess: true,
      fingerprint: async () => fingerprint,
      metadata: { filename: selected.name, match_id: String(props.id), label: label.value.trim(), content },
      async onBeforeRequest(req) {
        if (!text || req.getMethod() !== 'PATCH' || !upload.url || notesSavedFor === upload.url) return
        const url = new URL(upload.url, location.origin)
        if (url.origin !== location.origin || !url.pathname.startsWith('/uploads/')) {
          throw new Error('Nieprawidłowy adres przesyłania.')
        }
        await request(`${url.pathname}/notes`, {
          method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
          body: JSON.stringify({ text }),
        })
        notesSavedFor = upload.url
      },
      onShouldRetry(err) {
        if (err instanceof ApiError) return err.status === 0 || err.status >= 500
        const code = err.originalResponse?.getStatus()
        return code === undefined || code === 423 || (code >= 500 && code !== 501 && code !== 507)
          || (code === 409 && err.originalRequest?.getMethod() === 'PATCH')
      },
      onProgress(sent, total) {
        if (attempt === current) progress.value = total ? sent / total : 0
      },
      onSuccess() {
        if (attempt !== current) return
        active = undefined
        uploading.value = false
        status.value = `${selected.name}: nagranie przesłane. Konwersja ruszy w tle.`
        files.value = files.value?.slice(1) ?? null
        notes.value = ''
        label.value = ''
        periods.value = []
        emit('uploaded')
      },
      onError(err) {
        if (attempt !== current) return
        const body = err instanceof DetailedError ? err.originalResponse?.getBody() : null
        const prior = err instanceof DetailedError ? err.originalResponse?.getHeader('X-Active-Upload') : null
        if (prior && /^\/uploads\/[A-Za-z0-9_-]+$/.test(prior)) unfinished.value = prior
        try {
          const detail: unknown = JSON.parse(body || '{}').detail
          error.value = typeof detail === 'string' ? detail
            : err instanceof ApiError ? err.message : 'Przesyłanie zatrzymane. Spróbuj ponownie.'
        } catch {
          error.value = 'Przesyłanie zatrzymane. Spróbuj ponownie.'
        }
        active = undefined
        uploading.value = false
      },
    })
    active = upload
    const previous = (await upload.findPreviousUploads())[0]
    if (attempt !== current) return
    if (previous) upload.resumeFromPreviousUpload(previous)
    upload.start()
  } catch (err) {
    if (attempt !== current) return
    error.value = errorMessage(err)
    active = undefined
    uploading.value = false
  }
}

async function pause() {
  ++attempt
  const upload = active
  active = undefined
  try {
    await upload?.abort()
    status.value = 'Przesyłanie wstrzymane. Możesz je wznowić.'
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    uploading.value = false
  }
}

async function cancelPrevious() {
  if (!unfinished.value || cancelling.value) return
  cancelling.value = true
  error.value = ''
  try {
    await request(unfinished.value, {
      method: 'DELETE', headers: { ...await csrfHeaders(), 'Tus-Resumable': '1.0.0' },
    })
    unfinished.value = ''
    status.value = 'Poprzednie przesyłanie zostało anulowane.'
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    confirmation.value = false
    cancelling.value = false
  }
}

onBeforeUnmount(() => {
  ++attempt
  void active?.abort().catch(() => undefined)
})
</script>

<template>
  <q-form class="q-gutter-sm q-mt-md" @submit="start">
    <h3 class="text-h6">Dodaj nagranie</h3>
    <q-file v-model="files" outlined multiple use-chips label="Pliki wideo" accept="video/*,.mkv,.mov,.mp4,.avi,.ts" :disable="uploading" />
    <p v-if="file && files && files.length > 1" class="muted">Teraz przesyłasz {{ file.name }}. Wybierz ustawienia dla każdego pliku osobno.</p>
    <q-input v-model="label" outlined label="Etykieta (opcjonalnie)" maxlength="100" :disable="uploading" />
    <q-select v-model="periods" :options="settings.periods" outlined multiple use-chips label="Kwarty w pliku" hint="Jeśli nie wybierzesz kwart, nagranie zostanie zapisane jako cały mecz." :disable="uploading" />
    <q-input v-if="settings.can_add_notes" v-model="notes" outlined type="textarea" label="Notatki do znaczników (opcjonalnie)" :maxlength="settings.notes_max_chars" :disable="uploading" />
    <q-banner v-if="error" class="error-banner" role="alert">{{ error }}</q-banner>
    <p v-if="status" role="status">{{ status }}</p>
    <q-linear-progress v-if="uploading" :value="progress" size="8px" />
    <div class="row q-gutter-sm">
      <q-btn type="submit" color="primary" label="Prześlij nagranie" :disable="!file || uploading" />
      <q-btn v-if="uploading" flat label="Wstrzymaj" @click="pause" />
      <q-btn v-if="unfinished && !uploading" flat color="negative" label="Anuluj poprzednie przesyłanie" @click="confirmation = true" />
    </div>
    <ConfirmAction v-model="confirmation" title="Anulować niedokończone przesyłanie?" message="Przesłana część poprzedniego pliku zostanie usunięta." label="Anuluj przesyłanie" :busy="cancelling" @confirm="cancelPrevious" />
  </q-form>
</template>
