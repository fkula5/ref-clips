<script setup lang="ts">
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ConfirmAction from '../components/common/ConfirmAction.vue'
import { useResource } from '../composables/useResource'
import type { Assessment } from '../types/assessments'

const route = useRoute()
const router = useRouter()
const editing = computed(() => route.params.mode === 'edit')
const base = computed(() => `/self-assessments/${route.params.id}`)
const { data, error, loading, saving, refresh, save } = useResource<Assessment>(() => base.value + (editing.value ? '/edit' : ''))
const values = ref<Record<string, string>>({})
const clipId = ref<number | null>(null)
const confirmation = ref(false)
const notice = ref('')
const back = computed(() => data.value?.match_id
  ? { name: 'match-detail', params: { id: data.value.match_id } }
  : { name: 'self-assessments' })

watch(data, assessment => {
  if (assessment) values.value = { ...assessment.values }
})

async function persist(action: string) {
  if (!data.value) return
  const payload = new URLSearchParams({ ...values.value, action })
  data.value.rows.forEach(row => payload.append('row', String(row.id)))
  const result = await save<{ id: number; editing: boolean }>(`${base.value}/edit`, payload)
  if (!result) return
  clipId.value = null
  if (result.editing) {
    notice.value = 'Zapisano szkic.'
    refresh()
  } else {
    notice.value = 'Wysłano samoocenę.'
    await router.replace({ name: 'self-assessment', params: { id: result.id, mode: '' } })
  }
}

async function remove() {
  const result = await save(`${base.value}/delete`)
  confirmation.value = false
  if (result) await router.replace(back.value)
}

async function reopen() {
  if (await save(`${base.value}/reopen`)) refresh()
}

function print() { window.print() }
</script>

<template>
  <q-page class="matches-page document-page">
    <q-btn flat label="Wróć" :to="back" />
    <header class="page-heading">
      <div><h1>Samoocena</h1><p v-if="data" class="muted">{{ data.title }} · {{ data.author }} · {{ data.published ? 'Wysłana' : 'Szkic' }}</p></div>
    </header>
    <LoadingSkeleton v-if="loading && !data" variant="detail" label="Ładowanie samooceny" />
    <q-banner v-if="error" class="error-banner q-my-md" role="alert">{{ error }}</q-banner>
    <q-banner v-if="notice" class="notice-success q-my-md" role="status">{{ notice }}</q-banner>
    <template v-if="data">
      <div class="row q-gutter-sm q-mb-md print-hide">
        <q-btn v-if="editing" flat label="Podgląd" :to="{ name: 'self-assessment', params: { id: data.id, mode: '' } }" />
        <q-btn v-else-if="data.can_edit" color="primary" label="Edytuj szkic" :to="{ name: 'self-assessment', params: { id: data.id, mode: 'edit' } }" />
        <q-btn v-if="!editing" flat label="Pobierz PDF" :href="`${base}/pdf`" />
        <q-btn v-if="!editing && data.published" flat label="Pobierz ZIP z klipami" :href="`${base}/zip`" />
        <q-btn v-if="!editing" flat label="Drukuj" @click="print" />
        <q-btn v-if="data.can_delete" flat color="negative" label="Usuń szkic" @click="confirmation = true" />
        <q-btn v-if="data.can_reopen" flat color="primary" label="Przywróć do edycji" :loading="saving" @click="reopen" />
      </div>
      <q-form class="q-gutter-md" @submit="persist('save')">
        <q-card flat bordered>
          <q-card-section v-if="editing && !data.match_id" class="q-gutter-sm">
            <h2 class="text-h6">Mecz spoza systemu</h2>
            <q-input v-model="values.match_date" outlined type="date" stack-label label="Data meczu" />
            <q-input v-for="field in data.header_fields" :key="field.key" v-model="values[field.key]" outlined :label="field.label" maxlength="200" :list="field.key === 'league' ? 'assessment-leagues' : undefined" />
            <datalist id="assessment-leagues"><option v-for="league in data.league_names" :key="league" :value="league" /></datalist>
          </q-card-section>
          <q-card-section v-else>
            <h2 class="text-h6">Mecz</h2>
            <p class="q-mb-sm">{{ [data.header.level, data.header.date, data.header.team_a, data.header.team_b].filter(Boolean).join(' · ') }}</p>
            <p class="q-mb-none">{{ [data.header.main_referee, data.header.assistants].filter(Boolean).join(' · ') }}</p>
          </q-card-section>
        </q-card>
        <q-card flat bordered>
          <q-card-section>
            <h2 class="text-h6">Klipy</h2>
            <p v-if="editing" class="muted">Do wysłania potrzeba co najmniej {{ data.min_clips }} opisanych klipów i odpowiedzi na wszystkie pytania.</p>
            <p v-if="!data.rows.length" class="muted">Brak klipów w samoocenie.</p>
            <q-card v-for="(row, index) in data.rows" :key="row.id" flat bordered class="q-mb-sm">
              <q-card-section class="q-gutter-sm">
                <strong>Klip {{ index + 1 }} · {{ row.manual ? 'Wpisany ręcznie' : row.name }}</strong>
                <q-btn v-if="row.clip_id" flat dense color="primary" :label="`Otwórz klip ${row.time}`" :to="{ name: 'clip-detail', params: { id: row.clip_id } }" target="_blank" />
                <q-input v-if="row.manual && editing" v-model="values[row.name_key]" outlined label="Nazwa klipu" maxlength="200" />
                <p v-else-if="row.manual" class="q-mb-none">{{ values[row.name_key] }}</p>
                <q-input v-if="editing" v-model="values[row.desc_key]" outlined type="textarea" autogrow label="Opis klipu" />
                <p v-else class="preserve-lines q-mb-none">{{ values[row.desc_key] }}</p>
                <div v-if="editing" class="row q-gutter-xs">
                  <q-btn v-if="row.hint" flat dense label="Wstaw opis z klipu" @click="values[row.desc_key] = row.hint ?? ''" />
                  <q-btn flat dense icon="arrow_upward" aria-label="Przesuń wyżej" :disable="saving || index === 0" @click="persist(`up:${row.id}`)" />
                  <q-btn flat dense icon="arrow_downward" aria-label="Przesuń niżej" :disable="saving || index + 1 === data.rows.length" @click="persist(`down:${row.id}`)" />
                  <q-btn flat dense color="negative" label="Usuń wiersz" :disable="saving" @click="persist(`remove:${row.id}`)" />
                </div>
              </q-card-section>
            </q-card>
            <div v-if="editing" class="row items-center q-gutter-sm">
              <q-btn flat color="primary" label="Dodaj wiersz ręcznie" :disable="saving" @click="persist('manual')" />
              <q-select v-if="data.available.length" v-model="clipId" class="col" :options="data.available" option-value="id" emit-value map-options outlined dense label="Klip z meczu" />
              <q-btn v-if="clipId" flat color="primary" label="Dodaj klip" :disable="saving" @click="persist(`add:${clipId}`)" />
            </div>
          </q-card-section>
        </q-card>
        <q-card flat bordered>
          <q-card-section class="q-gutter-sm">
            <h2 class="text-h6">Pytania</h2>
            <div v-for="field in data.questions" :key="field.key">
              <h3 class="text-subtitle1 q-mb-sm">{{ field.label }}</h3>
              <q-input v-if="editing" v-model="values[field.key]" outlined type="textarea" autogrow :aria-label="field.label" />
              <p v-else class="preserve-lines">{{ values[field.key] || 'Brak odpowiedzi.' }}</p>
            </div>
          </q-card-section>
        </q-card>
        <div v-if="editing" class="row q-gutter-sm">
          <q-btn type="submit" color="primary" label="Zapisz szkic" :loading="saving" />
          <q-btn outline color="primary" label="Wyślij samoocenę" :disable="saving" @click="persist('submit')" />
        </div>
      </q-form>
      <ConfirmAction v-model="confirmation" title="Usunąć szkic samooceny?" :message="data.title" label="Usuń szkic" :busy="saving" @confirm="remove" />
    </template>
  </q-page>
</template>

<style scoped>
.preserve-lines { white-space: pre-wrap; overflow-wrap: anywhere; max-width: 75ch; }
</style>
