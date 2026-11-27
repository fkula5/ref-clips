<script setup lang="ts">
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ConfirmAction from '../components/common/ConfirmAction.vue'
import { useResource } from '../composables/useResource'
import type { Sheet } from '../types/assessments'

const route = useRoute()
const router = useRouter()
const editing = computed(() => route.params.mode === 'edit')
const base = computed(() => `/sheets/${route.params.id}`)
const { data, error, loading, saving, refresh, save } = useResource<Sheet>(() => base.value + (editing.value ? '/edit' : ''))
const values = ref<Record<string, string>>({})
const confirmation = ref(false)
const notice = ref('')
watch(data, sheet => { if (sheet) values.value = { ...sheet.values } })

async function persist(action: 'save' | 'publish' | 'refresh') {
  const result = await save<{ id: number; editing: boolean; notes: string[] }>(`${base.value}/edit`, { ...values.value, action })
  if (!result) return
  if (result.editing) {
    notice.value = result.notes.join(' ') || 'Zapisano szkic.'
    refresh()
  } else {
    notice.value = action === 'publish' ? 'Opublikowano arkusz.' : 'Zapisano arkusz.'
    await router.replace({ name: 'sheet', params: { id: result.id, mode: '' } })
  }
}

async function remove() {
  const result = await save<{ match_id: number }>(`${base.value}/delete`)
  confirmation.value = false
  if (result) await router.replace({ name: 'match-detail', params: { id: result.match_id } })
}
</script>

<template>
  <q-page class="matches-page document-page">
    <q-btn flat label="Wróć do meczu" :to="data ? { name: 'match-detail', params: { id: data.match.id } } : { name: 'matches' }" />
    <header class="page-heading"><div><h1>Arkusz oceny sędziów</h1><p v-if="data" class="muted">{{ data.match.title }} · {{ data.author }} · {{ data.published ? 'Opublikowany' : 'Szkic' }}</p></div></header>
    <LoadingSkeleton v-if="loading && !data" variant="detail" label="Ładowanie arkusza oceny" />
    <q-banner v-if="error" class="error-banner q-my-md" role="alert">{{ error }}</q-banner>
    <q-banner v-if="notice" class="notice-success q-my-md" role="status">{{ notice }}</q-banner>
    <template v-if="data">
      <div class="row q-gutter-sm q-mb-md">
        <q-btn v-if="editing" flat label="Podgląd" :to="{ name: 'sheet', params: { id: data.id, mode: '' } }" />
        <q-btn v-else-if="data.can_edit" color="primary" label="Edytuj arkusz" :to="{ name: 'sheet', params: { id: data.id, mode: 'edit' } }" />
        <q-btn v-if="data.can_delete" flat color="negative" label="Usuń arkusz" @click="confirmation = true" />
      </div>
      <q-form class="sheet-form" @submit="persist('save')">
        <q-card flat bordered>
          <q-card-section v-if="editing" class="sheet-summary">
            <q-input v-model="values.result" outlined label="Wynik" />
            <q-select v-model="values.difficulty" :options="data.difficulties" emit-value map-options outlined label="Stopień trudności" />
          </q-card-section>
          <q-card-section v-else>
            <dl class="sheet-summary">
              <div><dt>Wynik</dt><dd>{{ values.result || '—' }}</dd></div>
              <div><dt>Stopień trudności</dt><dd>{{ data.difficulties.find(item => item.value === values.difficulty)?.label ?? '—' }}</dd></div>
            </dl>
          </q-card-section>
        </q-card>
        <q-banner v-if="editing && data.changes.length" class="notice-warning">
          Obsada meczu się zmieniła. {{ data.changes.join(' · ') }}
          <template #action><q-btn flat label="Zapisz i odśwież obsadę" :disable="saving" @click="persist('refresh')" /></template>
        </q-banner>
        <div class="sheet-columns">
          <q-card v-for="column in data.columns" :key="column.id" flat bordered>
            <q-card-section>
              <h2 class="text-h6">{{ column.label }}</h2>
              <div v-if="editing" class="sheet-form">
                <q-input v-for="field in column.fields" :key="field.key" v-model="values[field.key]" outlined type="textarea" autogrow :label="field.label" />
                <q-input v-model="values[column.overall]" outlined type="textarea" autogrow label="Ocena ogólna" />
                <q-input v-model="values[column.recommendation]" outlined type="textarea" autogrow label="Rekomendacja obsadowa" />
              </div>
              <dl v-else class="sheet-entries">
                <div v-for="field in column.fields" :key="field.key"><dt>{{ field.label }}</dt><dd>{{ values[field.key] || '—' }}</dd></div>
                <div><dt>Ocena ogólna</dt><dd>{{ values[column.overall] || '—' }}</dd></div>
                <div><dt>Rekomendacja obsadowa</dt><dd>{{ values[column.recommendation] || '—' }}</dd></div>
              </dl>
            </q-card-section>
          </q-card>
        </div>
        <q-input v-if="editing" v-model="values.crew_note" outlined type="textarea" autogrow label="Uwaga o obsadzie sędziowskiej" />
        <q-card v-else-if="values.crew_note" flat bordered>
          <q-card-section>
            <h2 class="text-h6">Uwaga o obsadzie sędziowskiej</h2>
            <p class="sheet-note">{{ values.crew_note }}</p>
          </q-card-section>
        </q-card>
        <div v-if="editing" class="row q-gutter-sm">
          <q-btn color="primary" type="submit" :label="data.published ? 'Zapisz zmiany' : 'Zapisz szkic'" :loading="saving" />
          <q-btn v-if="!data.published && data.can_publish" outline color="primary" label="Opublikuj" :disable="saving" @click="persist('publish')" />
        </div>
      </q-form>
      <ConfirmAction v-model="confirmation" title="Usunąć arkusz oceny?" :message="data.match.title" label="Usuń arkusz" :busy="saving" @confirm="remove" />
    </template>
  </q-page>
</template>

<style scoped>
.sheet-form, .sheet-columns, .sheet-summary {
  display: grid;
  gap: 12px;
  min-width: 0;
}
.sheet-summary { grid-template-columns: repeat(auto-fit, minmax(min(100%, 190px), 1fr)); }
.sheet-columns { grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); }
dl, dd, .sheet-note { margin: 0; }
dt { font-weight: 650; }
dd { color: var(--text-muted); }
.sheet-entries > div + div { border-top: 1px solid var(--surface-border); margin-top: 8px; padding-top: 8px; }
dd, .sheet-note { white-space: pre-wrap; }
</style>
