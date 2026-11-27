<script setup lang="ts">
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import MatchFilters from '../components/matches/MatchFilters.vue'
import MatchListItem from '../components/matches/MatchListItem.vue'
import { useMatches } from '../composables/useMatches'
import { useSession } from '../composables/useSession'

const { user } = useSession()
const { filters, result, loading, error, refresh, applyFilters, changePage } = useMatches()
</script>

<template>
  <q-page class="matches-page">
    <header class="page-heading">
      <h1 id="matches-title">Mecze</h1>
      <q-btn v-if="user?.can_create_match" :to="{ name: 'match-create' }" color="primary" icon="add" label="Dodaj mecz" unelevated />
    </header>
    <section class="library-panel" aria-labelledby="matches-title">
      <div class="library-title">
        <span v-if="!loading && !error" class="match-count" aria-live="polite">Liczba meczów: {{ result.total }}</span>
        <q-btn flat round icon="refresh" aria-label="Odśwież mecze" :disable="loading" @click="refresh" />
      </div>
      <MatchFilters :model-value="filters" :levels="result.levels" :people="result.people" :groups="result.groups" :loading="loading" @apply="applyFilters" />
      <LoadingSkeleton v-if="loading" variant="matches" label="Ładowanie meczów" />
      <q-banner v-else-if="error" class="error-banner q-ma-md" role="alert">
        {{ error }}
        <template #action><q-btn flat label="Ponów" @click="refresh" /></template>
      </q-banner>
      <template v-else>
        <q-banner v-for="warning in result.errors" :key="warning" class="notice-warning q-ma-md">{{ warning }}</q-banner>
        <div v-if="!result.items.length" class="empty-state">
          <q-icon name="video_library" size="48px" />
          <h2>Brak meczów dla wybranych filtrów</h2>
          <p>Zmień filtry, aby zobaczyć inne wyniki.</p>
        </div>
        <div v-else class="match-list">
          <MatchListItem v-for="match in result.items" :key="match.id" :match="match" />
        </div>
      </template>
      <div v-if="result.pages > 1" class="pagination">
        <q-pagination :model-value="result.page" :max="result.pages" :max-pages="5" :disable="loading" color="primary" boundary-numbers @update:model-value="changePage" />
      </div>
    </section>
  </q-page>
</template>
