<script setup lang="ts">
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ConfirmAction from '../components/common/ConfirmAction.vue'
import CatalogForm from '../components/training/CatalogForm.vue'
import { useResource } from '../composables/useResource'
import type { SetDetail } from '../types/training'

const route = useRoute()
const router = useRouter()
const base = computed(() => `/sets/${route.params.id}`)
const { data, error, loading, saving, refresh, save } = useResource<SetDetail>(() => base.value)
const groupId = ref('')
const editing = ref(false)
const confirmOpen = ref(false)
const pending = ref<{ path: string; title: string; message: string }>()

async function change(path: string, fields: Record<string, string> = {}) {
  if (!await save(base.value + path, fields)) return false
  refresh()
  return true
}

function ask(path: string, title: string, message: string) {
  pending.value = { path, title, message }
  confirmOpen.value = true
}

async function confirm() {
  const path = pending.value?.path
  if (!path) return
  const result = await save(base.value + path)
  confirmOpen.value = false
  if (!result) return
  if (path === '/delete') await router.replace({ name: 'sets' })
  else refresh()
}

async function pin() {
  if (groupId.value && await change('/groups', { group_id: groupId.value })) groupId.value = ''
}

async function edit(values: Record<string, string>) {
  if (await change('/edit', values)) editing.value = false
}
</script>

<template>
  <q-page class="matches-page">
    <q-btn flat label="Zestawy szkoleniowe" :to="{ name: 'sets' }" />
    <LoadingSkeleton v-if="loading && !data" variant="detail" label="Ładowanie zestawu szkoleniowego" class="q-mt-md" />
    <q-banner v-if="error" class="error-banner q-my-md" role="alert">{{ error }}</q-banner>
    <template v-if="data">
      <header class="page-heading">
        <div><h1>{{ data.name }}</h1><p v-if="data.description">{{ data.description }}</p></div>
        <div v-if="data.can_edit" class="row q-gutter-sm">
          <q-btn flat label="Edytuj zestaw" @click="editing = !editing" />
          <q-btn flat color="negative" label="Usuń zestaw" @click="ask('/delete', 'Usunąć zestaw?', data.name)" />
        </div>
      </header>
      <q-card v-if="data.can_edit && editing" flat bordered class="q-mb-lg">
        <q-card-section><CatalogForm :key="data.id" :name="data.name" :description="data.description" :show-names="data.show_names" :saving="saving" submit-label="Zapisz zestaw" @save="edit" @cancel="editing = false" /></q-card-section>
      </q-card>
      <q-card flat bordered>
        <q-card-section>
          <h2 class="text-h6">Grupy</h2>
          <p v-if="!data.groups.length" class="muted">Zestaw nie jest przypięty do żadnej grupy.</p>
          <div v-else class="row q-gutter-sm">
            <q-chip v-for="group in data.groups" :key="group.id" :removable="data.can_edit && !saving" @remove="ask(`/groups/${group.id}/unpin`, 'Odpiąć zestaw od grupy?', group.name)">{{ group.name }}</q-chip>
          </div>
          <q-form v-if="data.can_edit && data.group_choices.length" class="row items-center q-gutter-sm q-mt-md" @submit="pin">
            <q-select v-model="groupId" :options="data.group_choices" emit-value map-options outlined dense label="Grupa szkoleniowa" class="col" />
            <q-btn type="submit" color="primary" label="Przypnij" :disable="!groupId" :loading="saving" />
          </q-form>
        </q-card-section>
        <q-separator />
        <q-card-section>
          <h2 class="text-h6">Klipy ({{ data.items.length }})</h2>
          <p v-if="!data.items.length" class="muted">Brak klipów w zestawie.</p>
          <q-list v-else separator>
            <q-item v-for="(clip, index) in data.items" :key="clip.id">
              <q-item-section>
                <q-item-label>{{ index + 1 }}. {{ clip.match }}</q-item-label>
                <q-item-label caption>{{ [clip.level, clip.official, clip.category].filter(Boolean).join(' · ') }}</q-item-label>
                <q-item-label v-if="clip.note" caption lines="2">{{ clip.note }}</q-item-label>
                <div class="row q-gutter-xs q-mt-sm">
                  <q-btn flat dense color="primary" label="Oglądaj" :to="{ name: 'set-clip', params: { id: data.id, clipId: clip.id } }" />
                  <template v-if="data.can_edit">
                    <q-btn flat dense icon="arrow_upward" aria-label="Przesuń w górę" :disable="index === 0 || saving || loading" @click="change(`/clips/${clip.id}/move`, { direction: 'up' })" />
                    <q-btn flat dense icon="arrow_downward" aria-label="Przesuń w dół" :disable="index + 1 === data.items.length || saving || loading" @click="change(`/clips/${clip.id}/move`, { direction: 'down' })" />
                    <q-btn flat dense color="negative" label="Usuń z zestawu" :disable="saving" @click="ask(`/clips/${clip.id}/remove`, 'Usunąć klip z zestawu?', clip.match)" />
                  </template>
                </div>
              </q-item-section>
            </q-item>
          </q-list>
          <q-btn v-if="data.can_edit" flat color="primary" label="Przejdź do biblioteki klipów" :to="{ name: 'clips' }" />
        </q-card-section>
      </q-card>
      <ConfirmAction v-if="pending" v-model="confirmOpen" :title="pending.title" :message="pending.message" label="Potwierdź" :busy="saving" @confirm="confirm" />
    </template>
  </q-page>
</template>
