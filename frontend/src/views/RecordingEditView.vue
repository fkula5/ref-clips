<script setup lang="ts">
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ConfirmAction from '../components/common/ConfirmAction.vue'
import { useResource } from '../composables/useResource'

interface VideoForm {
  id: number; name: string; label: string; match_id: number; purged: boolean; kind: string; checked: string[]; periods: string[]
}

const route = useRoute()
const router = useRouter()
const base = computed(() => `/videos/${route.params.id}`)
const { data, loading, saving, error, save } = useResource<VideoForm>(() => `${base.value}/edit`)
const label = ref('')
const kind = ref('full')
const periods = ref<string[]>([])
const confirmation = ref(false)
const token = ref('')
const warnings = ref<string[]>([])
const choices = computed(() => [
  { value: 'full', label: 'Cały mecz' },
  ...(data.value?.periods ?? []).map(value => ({ value, label: value })),
  { value: 'multi', label: 'Kilka kwart' },
])

watch(data, value => {
  if (!value) return
  label.value = value.label
  kind.value = value.kind
  periods.value = [...value.checked]
})

async function submit(confirmed = false) {
  const body = new URLSearchParams({ label: label.value, content_kind: kind.value, confirm_marks: confirmed ? token.value : '' })
  periods.value.forEach(period => body.append('periods', period))
  const result = await save<{ match_id: number; warnings?: string[]; confirm?: string }>(`${base.value}/update`, body)
  if (!result) { confirmation.value = false; return }
  if (result.confirm && result.warnings) {
    token.value = result.confirm
    warnings.value = result.warnings
    confirmation.value = true
  } else {
    await router.replace({ name: 'match-detail', params: { id: result.match_id } })
  }
}
</script>

<template>
  <q-page class="matches-page">
    <q-btn flat label="Wróć" :to="data ? { name: 'match-detail', params: { id: data.match_id } } : { name: 'matches' }" />
    <header class="page-heading"><div><h1>Edytuj nagranie</h1><p v-if="data">{{ data.name }}</p></div></header>
    <LoadingSkeleton v-if="loading && !data" variant="form" label="Ładowanie formularza nagrania" />
    <q-banner v-if="error" class="error-banner q-my-md" role="alert">{{ error }}</q-banner>
    <q-card v-if="data" flat bordered>
      <q-card-section>
        <q-form class="q-gutter-sm" @submit="submit()">
          <q-input v-model="label" outlined label="Etykieta" maxlength="100" />
          <template v-if="!data.purged">
            <q-select v-model="kind" outlined :options="choices" emit-value map-options label="Zawartość nagrania" />
            <q-select v-if="kind === 'multi'" v-model="periods" outlined multiple use-chips :options="data.periods" label="Wybierz co najmniej dwie kwarty" />
          </template>
          <q-btn type="submit" color="primary" label="Zapisz nagranie" :loading="saving" />
        </q-form>
      </q-card-section>
    </q-card>
    <ConfirmAction v-model="confirmation" title="Zmienić znaczniki kwart?" :message="warnings.join(' · ')" label="Zapisz i przelicz" :busy="saving" @confirm="submit(true)" />
  </q-page>
</template>
