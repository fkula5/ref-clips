<script setup lang="ts">
import { computed, ref } from 'vue'
import { errorMessage } from '../../api/client'
import { useSession } from '../../composables/useSession'
import type { ClipDetail } from '../../types/api'

const props = defineProps<{ id: number; choices: NonNullable<ClipDetail['set_choices']> }>()
const emit = defineEmits<{ saved: [] }>()
const { submit } = useSession()
const existing = ref<string | null>(null)
const name = ref('')
const saved = ref<number>()
const error = ref('')
const busy = ref(false)
const options = computed(() => props.choices.filter(set => !set.has_clip).map(set => ({ value: String(set.id), label: set.name })))

async function add() {
  if (busy.value || Boolean(existing.value) === Boolean(name.value.trim())) return
  busy.value = true
  error.value = ''
  saved.value = undefined
  try {
    const result = await submit<{ id: number }>(`/clips/${props.id}/sets`, {
      set_id: existing.value ?? '', new_name: name.value,
    })
    saved.value = result.id
    existing.value = null
    name.value = ''
    emit('saved')
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <q-card flat bordered class="q-mt-lg">
    <q-card-section>
      <h2 class="text-h6">Zestawy szkoleniowe</h2>
      <div class="row q-gutter-sm q-mb-md">
        <q-btn v-for="set in choices.filter(item => item.has_clip)" :key="set.id" flat color="primary" :label="set.name" :to="{ name: 'set-detail', params: { id: set.id } }" />
      </div>
      <q-banner v-if="error" class="error-banner q-mb-md" role="alert">{{ error }}</q-banner>
      <q-form class="q-gutter-sm" @submit="add">
        <q-select v-if="options.length" v-model="existing" :options="options" outlined clearable emit-value map-options label="Istniejący zestaw" :disable="busy || Boolean(name.trim())" />
        <q-input v-model="name" outlined label="Nazwa nowego zestawu" maxlength="100" :disable="busy || Boolean(existing)" />
        <q-btn type="submit" color="primary" label="Dodaj do zestawu" :loading="busy" :disable="!existing && !name.trim()" />
        <q-btn v-if="saved" flat color="primary" label="Otwórz zapisany zestaw" :to="{ name: 'set-detail', params: { id: saved } }" />
      </q-form>
    </q-card-section>
  </q-card>
</template>
