<script setup lang="ts">
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import CatalogForm from '../components/training/CatalogForm.vue'
import ConfirmAction from '../components/common/ConfirmAction.vue'
import { useResource } from '../composables/useResource'
import type { GroupDetail } from '../types/training'

const route = useRoute()
const router = useRouter()
const base = computed(() => `/groups/${route.params.id}`)
const { data, loading, saving, error, refresh, save } = useResource<GroupDetail>(() => {
  const days = typeof route.query.days === 'string' ? route.query.days : ''
  return `${base.value}?${new URLSearchParams({ days })}`
})
const editing = ref(false)
const referee = ref('')
const coach = ref('')
const confirmOpen = ref(false)
const pending = ref<{ path: string; title: string; message: string }>()

function ask(path: string, title: string, message: string) {
  pending.value = { path, title, message }
  confirmOpen.value = true
}

async function confirm() {
  const action = pending.value
  if (!action) return
  const result = await save<{ left?: boolean }>(base.value + action.path)
  confirmOpen.value = false
  if (!result) return
  if (action.path === '/delete' || result.left) await router.replace({ name: 'groups' })
  else refresh()
}

async function add(role: 'referees' | 'coaches') {
  const selected = role === 'referees' ? referee : coach
  if (!selected.value) return
  if (await save(`${base.value}/${role}`, { user_id: selected.value })) {
    selected.value = ''
    refresh()
  }
}

async function edit(values: Record<string, string>) {
  if (await save(`${base.value}/edit`, values)) {
    editing.value = false
    refresh()
  }
}
</script>

<template>
  <q-page class="matches-page">
    <q-btn flat label="Grupy szkoleniowe" :to="{ name: 'groups' }" />
    <LoadingSkeleton v-if="loading && !data" variant="detail" label="Ładowanie grupy" />
    <q-banner v-if="error" class="error-banner q-my-md" role="alert">{{ error }}</q-banner>
    <template v-if="data">
      <header class="page-heading">
        <div><h1>{{ data.name }}</h1><p v-if="data.description">{{ data.description }}</p></div>
        <div class="row q-gutter-sm">
          <q-btn color="primary" :label="`Do oceny (${data.review_count})`" :to="{ name: 'group-review', params: { id: data.id } }" />
          <q-btn v-if="data.can_manage" flat label="Edytuj grupę" @click="editing = !editing" />
          <q-btn v-if="data.can_manage" flat color="negative" label="Usuń grupę" @click="ask('/delete', 'Usunąć grupę?', 'Członkowie stracą dostęp do grupy.')" />
        </div>
      </header>
      <q-card v-if="editing && data.can_manage" flat bordered class="q-mb-lg">
        <q-card-section><CatalogForm :key="data.id" :name="data.name" :description="data.description" :saving="saving" submit-label="Zapisz grupę" @save="edit" @cancel="editing = false" /></q-card-section>
      </q-card>
      <q-card flat bordered>
        <q-card-section>
          <h2 class="text-h6">Przypięte zestawy</h2>
          <p v-if="!data.pinned.length" class="muted">Brak przypiętych zestawów.</p>
          <q-list v-else separator>
            <q-item v-for="set in data.pinned" :key="set.id" clickable :to="{ name: 'set-detail', params: { id: set.id } }">
              <q-item-section>{{ set.name }}</q-item-section><q-item-section side>{{ set.clips }} klipów</q-item-section>
            </q-item>
          </q-list>
        </q-card-section>
        <q-separator />
        <q-card-section>
          <h2 class="text-h6">Aktywność sędziów</h2>
          <q-select :model-value="data.days" :options="data.periods" outlined dense label="Okres (dni)" :disable="loading" class="q-mb-sm" @update:model-value="days => router.replace({ query: { days: String(days) } })" />
          <p v-if="!data.activity.length" class="muted">Brak sędziów w grupie.</p>
          <q-list v-else separator>
            <q-item v-for="member in data.activity" :key="member.id">
              <q-item-section>
                <q-item-label>{{ member.name }}</q-item-label>
                <q-item-label caption>Nagrania {{ member.recordings }} · Znaczniki {{ member.markers }} · Opisane {{ member.described }}</q-item-label>
                <q-item-label v-if="member.last" caption>Ostatnia aktywność: {{ member.last }}</q-item-label>
                <div v-if="data.can_manage"><q-btn flat dense color="negative" label="Usuń z grupy" @click="ask(`/referees/${member.id}/remove`, 'Usunąć sędziego?', member.name)" /></div>
              </q-item-section>
            </q-item>
          </q-list>
          <q-form v-if="data.can_manage && data.candidates.referee.length" class="row items-center q-gutter-sm q-mt-md" @submit="add('referees')">
            <q-select v-model="referee" :options="data.candidates.referee" emit-value map-options outlined dense label="Sędzia" class="col" />
            <q-btn type="submit" color="primary" label="Dodaj sędziego" :disable="!referee" :loading="saving" />
          </q-form>
        </q-card-section>
        <q-separator />
        <q-card-section>
          <h2 class="text-h6">Szkoleniowcy</h2>
          <q-list separator>
            <q-item v-for="member in data.coaches" :key="member.id">
              <q-item-section>{{ member.name }}</q-item-section>
              <q-item-section v-if="data.can_manage" side><q-btn flat dense color="negative" label="Usuń z grupy" @click="ask(`/coaches/${member.id}/remove`, 'Usunąć szkoleniowca?', member.name)" /></q-item-section>
            </q-item>
          </q-list>
          <q-form v-if="data.can_manage && data.candidates.coach.length" class="row items-center q-gutter-sm q-mt-md" @submit="add('coaches')">
            <q-select v-model="coach" :options="data.candidates.coach" emit-value map-options outlined dense label="Szkoleniowiec" class="col" />
            <q-btn type="submit" color="primary" label="Dodaj szkoleniowca" :disable="!coach" :loading="saving" />
          </q-form>
        </q-card-section>
      </q-card>
      <ConfirmAction v-if="pending" v-model="confirmOpen" :title="pending.title" :message="pending.message" label="Usuń" :busy="saving" @confirm="confirm" />
    </template>
  </q-page>
</template>
