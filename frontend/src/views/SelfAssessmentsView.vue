<script setup lang="ts">
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useResource } from '../composables/useResource'
import type { AssessmentList } from '../types/assessments'

const route = useRoute()
const router = useRouter()
const { data, loading, error, saving, save } = useResource<AssessmentList>(() => {
  const page = typeof route.query.page === 'string' ? route.query.page : '1'
  return `/self-assessments?${new URLSearchParams({ page })}`
})
const sections = computed(() => [
  { label: 'Moje samooceny', items: data.value?.mine ?? [] },
  { label: 'Wysłane samooceny', items: data.value?.submitted ?? [] },
])

async function create() {
  const result = await save<{ id: number }>('/self-assessments/new')
  if (result) await router.push({ name: 'self-assessment', params: { id: result.id, mode: 'edit' } })
}
</script>

<template>
  <q-page class="matches-page">
    <header class="page-heading"><h1>Samooceny</h1><q-btn v-if="data?.can_create" color="primary" label="Dodaj samoocenę meczu spoza systemu" :loading="saving" @click="create" /></header>
    <LoadingSkeleton v-if="loading && !data" variant="list" label="Ładowanie listy samoocen" />
    <q-banner v-if="error" class="error-banner q-my-md" role="alert">{{ error }}</q-banner>
    <template v-if="data">
      <p v-if="sections.every(section => !section.items.length)" class="muted">Brak samoocen.</p>
      <section v-for="section in sections.filter(item => item.items.length)" :key="section.label" class="q-mb-lg">
        <h2 class="text-h6">{{ section.label }}</h2>
        <q-list bordered separator class="surface-panel rounded-borders">
          <q-item v-for="item in section.items" :key="item.id" clickable :to="{ name: 'self-assessment', params: { id: item.id, mode: item.published ? '' : 'edit' } }">
            <q-item-section><q-item-label>{{ item.title }}</q-item-label><q-item-label caption>{{ item.author }}</q-item-label></q-item-section>
            <q-item-section side>{{ item.published ? 'Wysłana' : 'Szkic' }}</q-item-section>
          </q-item>
        </q-list>
      </section>
      <q-pagination v-if="data.pages > 1" :model-value="data.page" :max="data.pages" boundary-numbers @update:model-value="page => router.replace({ query: { page: String(page) } })" />
    </template>
  </q-page>
</template>
