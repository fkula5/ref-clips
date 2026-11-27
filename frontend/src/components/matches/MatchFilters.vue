<script setup lang="ts">
import type { MatchFilters, SelectOption } from '../../types/api'
import ResponsiveFilters from '../common/ResponsiveFilters.vue'

const filters = defineModel<MatchFilters>({ required: true })
defineProps<{ levels: string[]; people: SelectOption[]; groups: SelectOption[]; loading: boolean }>()
defineEmits<{ apply: [] }>()
</script>

<template>
  <ResponsiveFilters v-slot="{ close }" class="match-filters">
    <q-form class="match-filter-form" @submit="$emit('apply'); close()">
      <div class="filter-grid">
        <q-select v-model="filters.level" :options="levels" outlined dense clearable label="Liga" />
        <q-select v-model="filters.person" :options="people" outlined dense clearable emit-value map-options label="Sędzia" />
        <q-select v-model="filters.group" :options="groups" outlined dense clearable emit-value map-options label="Grupa" />
        <q-input v-model="filters.dateFrom" outlined dense type="date" label="Data od" stack-label />
        <q-input v-model="filters.dateTo" outlined dense type="date" label="Data do" stack-label />
      </div>
      <div class="filter-actions">
        <q-checkbox v-model="filters.mine" label="Tylko moje" color="primary" />
        <q-btn type="submit" unelevated color="primary" label="Filtruj" :loading="loading" />
        <q-btn flat label="Wyczyść" :to="{ name: 'matches' }" @click="close()" />
      </div>
    </q-form>
  </ResponsiveFilters>
</template>

<style scoped>
.match-filters { padding: 0 var(--panel-padding) 12px; }
.match-filter-form { padding-block: 4px; }
</style>
