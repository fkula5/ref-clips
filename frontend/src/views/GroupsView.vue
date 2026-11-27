<script setup lang="ts">
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import CatalogForm from '../components/training/CatalogForm.vue'
import { useResource } from '../composables/useResource'
import type { GroupList } from '../types/training'

const router = useRouter()
const creating = ref(false)
const { data, loading, saving, error, save } = useResource<GroupList>(() => '/groups')

async function create(values: Record<string, string>) {
  const result = await save<{ id: number }>('/groups', values)
  if (result) await router.push({ name: 'group-detail', params: { id: result.id } })
}
</script>

<template>
  <q-page class="matches-page">
    <header class="page-heading">
      <h1>Grupy szkoleniowe</h1>
      <q-btn v-if="data?.can_create && !creating" color="primary" label="Dodaj grupę" @click="creating = true" />
    </header>
    <LoadingSkeleton v-if="loading && !data" variant="list" label="Ładowanie grup szkoleniowych" />
    <q-banner v-if="error" class="error-banner q-my-md" role="alert">{{ error }}</q-banner>
    <q-card v-if="creating" flat bordered class="q-mb-lg">
      <q-card-section><CatalogForm :saving="saving" submit-label="Utwórz grupę" @save="create" @cancel="creating = false" /></q-card-section>
    </q-card>
    <p v-if="data && !data.items.length" class="muted">Brak grup szkoleniowych.</p>
    <q-card v-for="group in data?.items" :key="group.id" flat bordered class="q-mb-md">
      <q-card-section>
        <h2 class="text-h6 q-mb-sm">{{ group.name }}</h2>
        <p v-if="group.description">{{ group.description }}</p>
        <q-btn v-if="group.viewable" dense flat color="primary" label="Otwórz grupę" :to="{ name: 'group-detail', params: { id: group.id } }" />
        <q-list v-if="group.pinned.length" separator>
          <q-item v-for="set in group.pinned" :key="set.id" clickable :to="{ name: 'set-detail', params: { id: set.id } }">
            <q-item-section><q-item-label>{{ set.name }}</q-item-label><q-item-label caption>Klipy: {{ set.clips }}</q-item-label></q-item-section>
          </q-item>
        </q-list>
      </q-card-section>
    </q-card>
  </q-page>
</template>
