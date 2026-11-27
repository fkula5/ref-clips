<script setup lang="ts">
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useResource } from '../composables/useResource'
import type { SelectOption } from '../types/api'
import type { NamedItem } from '../types/training'

interface Tally { clips: number; rated: number; unrated: number; verdicts: Record<string, number> }
interface FeedbackRow { id: number; clip_id: number; author: string; date: string; text: string; verdict?: string }
interface Profile {
  name: string; active: boolean; person: string; period: string; since: string;
  periods: SelectOption[]; verdicts: Record<string, string>; match_count: number;
  total: Tally; uncategorised: number; page: number; pages: number; groups: NamedItem[];
  matches: (NamedItem & { level: string; function: string; tally: Tally })[];
  categories: (NamedItem & { tally: Tally })[];
  clips: { id: number; match: string; category: string; time: string; description: string }[];
  ratings: FeedbackRow[]; comments: FeedbackRow[]
}
const route = useRoute()
const router = useRouter()
const { data, error, loading } = useResource<Profile>(() => {
  const params = new URLSearchParams()
  for (const name of ['range', 'page']) {
    const value = route.query[name]
    if (typeof value === 'string') params.set(name, value)
  }
  return `/referees/${route.params.id}?${params}`
})
const feeds = computed(() => [
  { name: 'Ostatnie oceny', rows: data.value?.ratings ?? [], hash: '#oceny' },
  { name: 'Ostatnie komentarze', rows: data.value?.comments ?? [], hash: '#komentarze' },
])

function clipQuery(filters: Record<string, string> = {}) {
  return { name: 'clips', query: { person: data.value?.person, since: data.value?.since || undefined, ...filters } }
}
</script>

<template>
  <q-page class="matches-page">
    <header class="page-heading"><div><h1>{{ data?.name ?? 'Profil sędziego' }}</h1><p v-if="data && !data.active">Konto nieaktywne</p></div></header>
    <LoadingSkeleton v-if="loading && !data" variant="detail" label="Ładowanie profilu sędziego" />
    <q-banner v-if="error" class="error-banner q-my-md" role="alert">{{ error }}</q-banner>
    <template v-if="data">
      <div v-if="data.groups.length" class="row q-gutter-sm q-mb-md">
        <q-btn v-for="group in data.groups" :key="group.id" flat color="primary" :label="group.name" :to="{ name: 'group-detail', params: { id: group.id } }" />
      </div>
      <q-select :model-value="data.period" :options="data.periods" emit-value map-options outlined label="Okres" class="q-mb-md" @update:model-value="range => router.replace({ query: { range } })" />
      <q-card flat bordered class="q-mb-md">
        <q-card-section class="row q-gutter-sm">
          <q-chip>Mecze: {{ data.match_count }}</q-chip>
          <q-btn flat color="primary" :label="`Klipy: ${data.total.clips}`" :to="clipQuery()" />
          <q-btn flat color="primary" :label="`Ocenione: ${data.total.rated}`" :to="clipQuery({ rating: 'any' })" />
          <q-btn v-for="(label, verdict) in data.verdicts" :key="verdict" flat :label="`${label}: ${data.total.verdicts[verdict]}`" :to="clipQuery({ rating: verdict })" />
        </q-card-section>
      </q-card>
      <q-card flat bordered class="q-mb-md">
        <q-card-section>
          <h2 class="text-h6">Mecze</h2>
          <p v-if="!data.matches.length" class="muted">Brak meczów w tym okresie.</p>
          <q-list v-else separator>
            <q-item v-for="match in data.matches" :key="match.id">
              <q-item-section>
                <RouterLink :to="{ name: 'match-detail', params: { id: match.id } }">{{ match.name }}</RouterLink>
                <q-item-label caption>{{ match.level }} · {{ match.function }}</q-item-label>
                <div class="row">
                  <q-btn flat dense color="primary" :label="`Klipy: ${match.tally.clips}`" :to="clipQuery({ match_id: String(match.id) })" />
                  <q-btn v-for="(label, verdict) in data.verdicts" :key="verdict" flat dense :label="`${label}: ${match.tally.verdicts[verdict]}`" :to="clipQuery({ match_id: String(match.id), rating: verdict })" />
                </div>
              </q-item-section>
            </q-item>
          </q-list>
          <q-pagination v-if="data.pages > 1" :model-value="data.page" :max="data.pages" boundary-numbers @update:model-value="page => router.replace({ query: { ...route.query, page: String(page) } })" />
        </q-card-section>
      </q-card>
      <q-card flat bordered class="q-mb-md">
        <q-card-section>
          <h2 class="text-h6">Oceny według kategorii</h2>
          <p v-if="!data.categories.length" class="muted">Brak kategorii w tym okresie.</p>
          <q-list separator>
            <q-item v-for="category in data.categories" :key="category.id">
              <q-item-section>
                <q-item-label>{{ category.name }}</q-item-label>
                <div class="row">
                  <q-btn flat dense color="primary" :label="`Klipy: ${category.tally.clips}`" :to="clipQuery({ category_id: String(category.id) })" />
                  <q-btn v-for="(label, verdict) in data.verdicts" :key="verdict" flat dense :label="`${label}: ${category.tally.verdicts[verdict]}`" :to="clipQuery({ category_id: String(category.id), rating: verdict })" />
                </div>
              </q-item-section>
            </q-item>
          </q-list>
          <p class="muted q-mb-none">Klipy są wybierane do analizy. Te liczby nie mierzą skuteczności sędziego.</p>
        </q-card-section>
      </q-card>
      <q-card flat bordered class="q-mb-md">
        <q-card-section>
          <h2 class="text-h6">Ostatnie klipy</h2>
          <p v-if="!data.clips.length" class="muted">Brak klipów.</p>
          <q-list separator>
            <q-item v-for="clip in data.clips" :key="clip.id" clickable :to="{ name: 'clip-detail', params: { id: clip.id } }">
              <q-item-section><q-item-label>{{ clip.match }} · {{ clip.time }}</q-item-label><q-item-label caption>{{ clip.category }} {{ clip.description }}</q-item-label></q-item-section>
            </q-item>
          </q-list>
          <q-btn flat color="primary" label="Wszystkie klipy sędziego" :to="clipQuery({ since: '' })" />
        </q-card-section>
      </q-card>
      <q-card v-for="feed in feeds" :key="feed.name" flat bordered class="q-mb-md">
        <q-card-section>
          <h2 class="text-h6">{{ feed.name }}</h2>
          <p v-if="!feed.rows.length" class="muted">Brak wpisów.</p>
          <q-list separator>
            <q-item v-for="row in feed.rows" :key="row.id" clickable :to="{ name: 'clip-detail', params: { id: row.clip_id }, hash: feed.hash }">
              <q-item-section><q-item-label>{{ row.author }} · {{ row.date }}</q-item-label><q-item-label caption lines="2">{{ row.verdict }} {{ row.text }}</q-item-label></q-item-section>
            </q-item>
          </q-list>
        </q-card-section>
      </q-card>
    </template>
  </q-page>
</template>
