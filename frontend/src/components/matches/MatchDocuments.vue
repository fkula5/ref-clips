<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { errorMessage, request } from '../../api/client'
import { useSession } from '../../composables/useSession'
import type { MatchDetail } from '../../types/api'
import ConfirmAction from '../common/ConfirmAction.vue'

const props = defineProps<{ id: number; documents: MatchDetail['documents'] }>()
const emit = defineEmits<{ saved: [] }>()
const session = useSession()
const router = useRouter()
const error = ref('')
const busy = ref(false)
const files = ref<File[] | null>(null)
const confirmOpen = ref(false)
const pending = ref<{ id: number; name: string }>()

async function run(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try { await action() } catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}

function open(kind: 'sheets' | 'self-assessments') {
  return run(async () => {
    const result = await session.submit<{ id: number; editing: boolean }>(`/matches/${props.id}/${kind}`)
    await router.push({ name: kind === 'sheets' ? 'sheet' : 'self-assessment',
      params: { id: result.id, mode: result.editing ? 'edit' : '' } })
  })
}

function upload() {
  if (!files.value?.length) return
  const body = new FormData()
  files.value.forEach(file => body.append('files', file))
  return run(async () => {
    await request(`/matches/${props.id}/scoresheets`, { method: 'POST', headers: await session.csrfHeaders(), body })
    files.value = null
    emit('saved')
  })
}

function remove() {
  if (!pending.value) return
  return run(async () => {
    await session.submit(`/matches/${props.id}/scoresheets/${pending.value?.id}/delete`)
    confirmOpen.value = false
    emit('saved')
  })
}
</script>

<template>
  <q-card flat bordered class="q-mb-lg">
    <q-banner v-if="error" class="error-banner q-ma-md" role="alert">{{ error }}</q-banner>
    <q-card-section v-if="documents.sheets.length || documents.can_start_sheet">
      <h2 class="text-h6" id="arkusz">Arkusze oceny</h2>
      <q-list separator>
        <q-item v-for="sheet in documents.sheets" :key="sheet.id" clickable :to="{ name: 'sheet', params: { id: sheet.id, mode: sheet.can_edit && !sheet.published ? 'edit' : '' } }">
          <q-item-section>{{ sheet.author }}</q-item-section><q-item-section side>{{ sheet.published ? 'Opublikowany' : 'Szkic' }}</q-item-section>
        </q-item>
      </q-list>
      <q-btn v-if="documents.can_start_sheet" color="primary" label="Wypełnij arkusz" :loading="busy" @click="open('sheets')" />
    </q-card-section>
    <q-card-section v-if="documents.assessments.length || documents.can_start_assessment">
      <h2 class="text-h6" id="samoocena">Samooceny</h2>
      <q-list separator>
        <q-item v-for="sheet in documents.assessments" :key="sheet.id" clickable :to="{ name: 'self-assessment', params: { id: sheet.id, mode: sheet.can_edit ? 'edit' : '' } }">
          <q-item-section>{{ sheet.author }}</q-item-section><q-item-section side>{{ sheet.published ? 'Wysłana' : 'Szkic' }}</q-item-section>
        </q-item>
      </q-list>
      <q-btn v-if="documents.can_start_assessment" color="primary" label="Wypełnij samoocenę" :loading="busy" @click="open('self-assessments')" />
    </q-card-section>
    <q-card-section id="protokol">
      <h2 class="text-h6">Protokół meczu</h2>
      <p v-if="!documents.protocol.files.length" class="muted">Brak załączników.</p>
      <q-list v-else separator>
        <q-item v-for="file in documents.protocol.files" :key="file.id">
          <q-item-section>
            <q-item-label>{{ file.name }}</q-item-label>
            <q-item-label caption>{{ (file.size / 1024 / 1024).toFixed(1) }} MB</q-item-label>
            <div class="row q-gutter-xs">
              <q-btn v-if="file.inline" flat dense label="Podgląd" :href="`/matches/${id}/scoresheets/${file.id}/file`" target="_blank" rel="noopener" />
              <q-btn flat dense label="Pobierz" :href="`/matches/${id}/scoresheets/${file.id}/download`" />
              <q-btn v-if="documents.protocol.can_manage" flat dense color="negative" label="Usuń plik" @click="pending = file; confirmOpen = true" />
            </div>
          </q-item-section>
        </q-item>
      </q-list>
      <q-form v-if="documents.protocol.can_manage && documents.protocol.files.length < documents.protocol.max_files" class="q-gutter-sm q-mt-md" @submit="upload">
        <q-file v-model="files" multiple use-chips outlined label="Pliki protokołu" :accept="documents.protocol.accept" :max-file-size="documents.protocol.max_bytes" :max-files="documents.protocol.max_files - documents.protocol.files.length" :disable="busy" @rejected="error = 'Nie można dołączyć pliku. Sprawdź typ, rozmiar i liczbę plików.'" />
        <q-btn type="submit" color="primary" label="Dodaj pliki" :loading="busy" :disable="!files?.length" />
      </q-form>
    </q-card-section>
    <ConfirmAction v-if="pending" v-model="confirmOpen" title="Usunąć załącznik protokołu?" :message="pending.name" label="Usuń plik" :busy="busy" @confirm="remove" />
  </q-card>
</template>
