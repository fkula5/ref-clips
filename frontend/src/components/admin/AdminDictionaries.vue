<script setup lang="ts">
import LoadingSkeleton from '../common/LoadingSkeleton.vue'
import { computed, ref } from 'vue'
import ConfirmAction from '../common/ConfirmAction.vue'
import { useResource } from '../../composables/useResource'

interface Entry { id: number; name: string; active: boolean; used: number; group?: string; aliases?: string; protected?: boolean }
const props = defineProps<{ kind: string; title: string }>()
const base = computed(() => `/admin/${props.kind}`)
const { data, error, loading, saving, refresh, save } = useResource<{ items: Entry[]; groups?: string[] }>(() => base.value)
const editing = ref<Entry | null>(null)
const draft = ref({ name: '', group: '', aliases: '', merge: false })
const notice = ref('')
const confirmDelete = ref(false)
const deleting = ref<Entry | null>(null)
const adding = ref(false)
const sections = computed(() => {
  const items = data.value?.items ?? []
  return data.value?.groups?.map(group => ({ name: group, items: items.filter(item => item.group === group) }))
    ?? [{ name: '', items }]
})

function edit(item: Entry | null) {
  editing.value = item
  adding.value = !item
  draft.value = { name: item?.name ?? '', group: item?.group ?? data.value?.groups?.[0] ?? '', aliases: item?.aliases ?? '', merge: false }
}

async function change(path: string, fields: Record<string, string> = {}) {
  notice.value = ''
  const result = await save<{ notice: string }>(base.value + path, fields)
  if (!result) return false
  notice.value = result.notice
  refresh()
  return true
}

async function submit() {
  const fields = { ...draft.value, merge: draft.value.merge ? '1' : '0' }
  if (await change(editing.value ? `/${editing.value.id}/update` : '', fields)) {
    editing.value = null
    adding.value = false
  }
}

async function remove() {
  if (deleting.value && await change(`/${deleting.value.id}/delete`)) confirmDelete.value = false
}
</script>

<template>
  <section>
    <header class="page-heading"><h2 class="text-h5">{{ title }}</h2><q-btn color="primary" label="Dodaj pozycję" :disable="loading || !data" @click="edit(null)" /></header>
    <LoadingSkeleton v-if="loading && !data" variant="list" label="Ładowanie pozycji słownika" />
    <q-banner v-if="notice" class="notice-success q-my-md" role="status">{{ notice }}</q-banner>
    <q-banner v-if="error" class="error-banner q-my-md" role="alert">{{ error }}</q-banner>
    <q-card v-if="editing || adding" flat bordered class="q-my-md">
      <q-card-section>
        <q-form class="q-gutter-sm" @submit="submit">
          <q-input v-model="draft.name" outlined label="Nazwa" maxlength="100" :rules="[v => Boolean(v?.trim()) || 'Podaj nazwę.']" />
          <q-select v-if="data?.groups" v-model="draft.group" :options="data.groups" outlined label="Grupa" />
          <q-input v-if="data?.groups" v-model="draft.aliases" outlined label="Aliasy (po przecinku)" />
          <q-checkbox v-if="kind === 'leagues' && editing" v-model="draft.merge" label="Połącz z istniejącą ligą o tej nazwie" />
          <div class="row q-gutter-sm">
            <q-btn color="primary" type="submit" label="Zapisz" :loading="saving" />
            <q-btn flat label="Anuluj" :disable="saving" @click="editing = null; adding = false" />
          </div>
        </q-form>
      </q-card-section>
    </q-card>
    <template v-if="data">
      <section v-for="group in sections" :key="group.name" class="q-mb-lg">
        <h3 v-if="group.name" class="text-h6">{{ group.name }}</h3>
        <q-list v-if="group.items.length" bordered separator class="surface-panel rounded-borders">
          <q-item v-for="(item, index) in group.items" :key="item.id">
            <q-item-section>
              <q-item-label>{{ item.name }}</q-item-label>
              <q-item-label caption>{{ item.active ? 'Aktywna' : 'Nieaktywna' }} · Użycia: {{ item.used }}</q-item-label>
              <q-item-label v-if="item.aliases" caption>{{ item.aliases }}</q-item-label>
              <div class="row q-gutter-xs">
                <q-btn flat dense label="Edytuj" :disable="saving" @click="edit(item)" />
                <q-btn flat dense icon="arrow_upward" aria-label="Przesuń wyżej" :disable="index === 0 || saving || loading" @click="change(`/${item.id}/move`, { direction: 'up' })" />
                <q-btn flat dense icon="arrow_downward" aria-label="Przesuń niżej" :disable="index + 1 === group.items.length || saving || loading" @click="change(`/${item.id}/move`, { direction: 'down' })" />
                <q-btn v-if="!item.protected" flat dense :label="item.active ? 'Dezaktywuj' : 'Aktywuj'" :disable="saving" @click="change(`/${item.id}/active`, { active: item.active ? '0' : '1' })" />
                <q-btn v-if="!item.protected && !item.used" flat dense color="negative" label="Usuń" :disable="saving" @click="deleting = item; confirmDelete = true" />
              </div>
            </q-item-section>
          </q-item>
        </q-list>
        <p v-else class="muted">Brak pozycji.</p>
      </section>
    </template>
    <ConfirmAction v-if="deleting" v-model="confirmDelete" title="Usunąć pozycję?" :message="deleting.name" label="Usuń" :busy="saving" @confirm="remove" />
  </section>
</template>
