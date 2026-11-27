<script setup lang="ts">
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, errorMessage } from '../api/client'
import { fetchMatchForm } from '../api/matches'
import { useSession } from '../composables/useSession'
import type { CrewSlot, MatchFormData, TeamSide } from '../types/api'

const route = useRoute()
const router = useRouter()
const { submit, clear } = useSession()
const matchId = computed(() => typeof route.params.id === 'string' ? route.params.id : undefined)
const returnTo = computed(() => matchId.value
  ? { name: 'match-detail', params: { id: matchId.value } }
  : { name: 'matches' })
const form = ref<MatchFormData | null>(null)
const error = ref('')
const loading = ref(false)
const saving = ref(false)
const refresh = ref(0)
const teams: TeamSide[] = ['a', 'b']
const slots: CrewSlot[] = ['cc', 'u1', 'u2']
const leagueOptions = computed(() => {
  const options = (form.value?.levels ?? []).map(level => ({ value: level, label: level }))
  const extra = form.value?.extra_level
  if (extra) options.push({ value: extra, label: `${extra} (nieaktywna)` })
  return [{ value: '', label: 'Bez ligi' }, ...options]
})

watch([matchId, refresh], async ([id], _, onCleanup) => {
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  form.value = null
  error.value = ''
  loading.value = true
  try {
    const data = await fetchMatchForm(id, controller.signal)
    if (!controller.signal.aborted) form.value = data
  } catch (err) {
    if (controller.signal.aborted) return
    if (err instanceof ApiError && err.status === 401) {
      clear()
      await router.replace({ name: 'login', query: { next: route.fullPath } })
    } else {
      error.value = errorMessage(err)
    }
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })

async function save() {
  if (!form.value || saving.value) return
  const id = matchId.value
  saving.value = true
  error.value = ''
  try {
    const data = await submit<{ id: number }>(id ? `/matches/${id}` : '/matches', form.value.values)
    await router.replace({ name: 'match-detail', params: { id: data.id } })
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <q-page class="matches-page document-page">
    <header class="page-heading"><h1>{{ matchId ? 'Edytuj mecz' : 'Dodaj mecz' }}</h1></header>
    <LoadingSkeleton v-if="loading && !form" variant="form" label="Ładowanie formularza meczu" />
    <q-banner v-if="error" class="error-banner q-mb-md" role="alert">
      {{ error }}
      <template v-if="!form" #action><q-btn flat label="Ponów" @click="refresh++" /></template>
    </q-banner>
    <q-card v-if="form" flat bordered>
      <q-form @submit="save">
        <q-card-section class="row q-col-gutter-md">
          <q-input v-model="form.values.date" class="col-12 col-sm-6" type="date" outlined stack-label label="Data meczu" :disable="saving" :rules="[v => Boolean(v) || 'Podaj datę meczu.']" />
          <q-select v-model="form.values.level" class="col-12 col-sm-6" :options="leagueOptions" outlined emit-value map-options label="Liga" :disable="saving" />
        </q-card-section>
        <q-separator />
        <q-card-section class="row q-col-gutter-md">
          <section v-for="team in teams" :key="team" class="col-12 col-sm-6">
            <h2 class="text-h6">Drużyna {{ team.toUpperCase() }}</h2>
            <q-input v-model="form.values[`team_${team}_name`]" outlined label="Nazwa drużyny" maxlength="100" :disable="saving" class="q-mb-sm" />
            <q-input v-model="form.values[`team_${team}_color`]" outlined label="Kolor strojów" maxlength="50" :disable="saving" />
          </section>
        </q-card-section>
        <q-separator />
        <q-card-section>
          <h2 class="text-h6">Obsada sędziowska</h2>
          <p class="muted">CC i U1 są wymagani. Wybierz konto albo wpisz nazwisko sędziego.</p>
          <section v-for="slot in slots" :key="slot" class="q-mb-md">
            <h3 class="text-subtitle1">{{ slot.toUpperCase() }}{{ slot === 'u2' ? ' (opcjonalnie)' : '' }}</h3>
            <div class="row q-col-gutter-md">
              <q-select v-model="form.values[`${slot}_user`]" class="col-12 col-sm-6" :options="[{ value: '', label: 'Bez konta' }, ...form.referees]" outlined emit-value map-options label="Konto sędziego" :disable="saving" />
              <q-input v-model="form.values[`${slot}_name`]" class="col-12 col-sm-6" outlined label="Imię i nazwisko" maxlength="100" :disable="saving || Boolean(form.values[`${slot}_user`])" />
            </div>
          </section>
        </q-card-section>
        <q-card-actions class="q-pa-md">
          <q-btn color="primary" type="submit" label="Zapisz mecz" :loading="saving" />
          <q-btn flat label="Anuluj" :to="returnTo" />
        </q-card-actions>
      </q-form>
    </q-card>
    <q-btn v-else flat label="Wróć" :to="returnTo" />
  </q-page>
</template>
