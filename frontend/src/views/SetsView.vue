<script setup lang="ts">
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import CatalogForm from '../components/training/CatalogForm.vue'
import { useResource } from '../composables/useResource'
import type { SetList } from '../types/training'

const route = useRoute()
const router = useRouter()
const creating = ref(false)
const { data, error, loading, saving, save } = useResource<SetList>(() => {
  const page = typeof route.query.page === 'string' ? route.query.page : '1'
  return `/sets?${new URLSearchParams({ page })}`
})

async function create(values: Record<string, string>) {
  const result = await save<{ id: number }>('/sets', values)
  if (result) await router.push({ name: 'set-detail', params: { id: result.id } })
}
</script>

<template>
  <q-page class="matches-page">
    <header class="page-heading">
      <h1>Zestawy szkoleniowe</h1>
      <q-btn v-if="data?.can_edit && !creating" color="primary" label="Dodaj zestaw" @click="creating = true" />
    </header>
    <LoadingSkeleton v-if="loading && !data" variant="list" label="Ładowanie zestawów szkoleniowych" />
    <q-banner v-if="error" class="error-banner q-my-md" role="alert">{{ error }}</q-banner>
    <q-card v-if="creating" flat bordered class="q-mb-lg">
      <q-card-section><CatalogForm :saving="saving" submit-label="Utwórz zestaw" @save="create" @cancel="creating = false" /></q-card-section>
    </q-card>
    <template v-if="data">
      <p v-if="!data.items.length" class="muted">Brak zestawów szkoleniowych.</p>
      <q-list v-else bordered separator class="surface-panel rounded-borders">
        <q-item v-for="set in data.items" :key="set.id" clickable :to="{ name: 'set-detail', params: { id: set.id } }">
          <q-item-section>
            <q-item-label>{{ set.name }}</q-item-label>
            <q-item-label v-if="set.description" caption lines="2">{{ set.description }}</q-item-label>
            <q-item-label v-if="set.groups.length" caption>{{ set.groups.map(group => group.name).join(' · ') }}</q-item-label>
          </q-item-section>
          <q-item-section side>{{ set.clips }} klipów</q-item-section>
        </q-item>
      </q-list>
      <q-pagination v-if="data.pages > 1" class="q-mt-md" :model-value="data.page" :max="data.pages" boundary-numbers @update:model-value="page => router.replace({ query: { page: String(page) } })" />
    </template>
  </q-page>
</template>
