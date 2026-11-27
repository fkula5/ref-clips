<script setup lang="ts">
import type { Match } from '../../types/api'

defineProps<{ match: Match }>()
const dateFormatter = new Intl.DateTimeFormat('pl-PL', { day: 'numeric', month: 'long', year: 'numeric' })
const dateLabel = (value: string) => dateFormatter.format(new Date(`${value}T12:00:00`))
</script>

<template>
  <RouterLink :to="{ name: 'match-detail', params: { id: match.id } }" class="match-row">
    <div class="match-icon"><q-icon name="sports_basketball" size="28px" /></div>
    <div class="match-info">
      <div class="match-meta">
        <span>{{ dateLabel(match.date) }}</span>
        <span v-if="match.level" class="info-category">{{ match.level }}</span>
        <span v-else>Bez ligi</span>
      </div>
      <h3>{{ match.teams }}</h3>
      <p class="crew" :class="match.officials.length ? 'info-person' : 'info-context'">{{ match.officials.map(official => `${official.function}: ${official.name}`).join(' · ') || 'Nie podano obsady' }}</p>
    </div>
    <div class="match-summary">
      <q-badge class="state-badge" :data-status="match.state.code" :label="match.state.label" :title="match.state.detail" />
      <span><q-icon name="movie" /> {{ match.clips }} klipów</span>
      <small v-if="match.undescribed">Do opisania: {{ match.undescribed }}</small>
    </div>
  </RouterLink>
</template>
