<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { errorMessage } from '../../api/client'
import { useSession } from '../../composables/useSession'
import type { ClipDetail } from '../../types/api'

const props = defineProps<{ id: number; editor: NonNullable<ClipDetail['editor']>; shortcuts?: boolean }>()
const emit = defineEmits<{ saved: [] }>()
const { submit } = useSession()
const fields = reactive({ ...props.editor.values })
const officials = computed(() => [...props.editor.officials, { value: 'team', label: 'Cały zespół' }])
const custom = computed(() => props.editor.categories.some(option => option.value === fields.category_id && option.custom))
const busy = ref(false)
const error = ref('')
const required = (value: string) => Boolean(value) || 'Wybierz wartość.'
const form = ref<{ submit: () => void }>()
const category = ref<{ focus: () => void }>()
const description = ref<{ focus: () => void }>()

function keyboard(event: KeyboardEvent) {
  if (!props.shortcuts || props.editor.blocker || busy.value || event.defaultPrevented) return
  if (event.ctrlKey && event.key === 'Enter') { event.preventDefault(); form.value?.submit(); return }
  if (event.altKey || event.ctrlKey || event.metaKey || event.target instanceof HTMLElement
      && event.target.closest('input, textarea, select, button, [contenteditable], [role="combobox"]')) return
  const key = event.key.toLowerCase()
  if (key === 'k') { event.preventDefault(); category.value?.focus() }
  else if (key === 'd') { event.preventDefault(); description.value?.focus() }
  else if (key === '0') { event.preventDefault(); fields.official = 'team' }
  else if (['1', '2', '3'].includes(key)) {
    const slot = ['CC', 'U1', 'U2'][Number(key) - 1]
    const official = props.editor.officials.find(item => item.label.startsWith(slot + ' '))
    if (official) { event.preventDefault(); fields.official = official.value }
  }
}

onMounted(() => window.addEventListener('keydown', keyboard))
onUnmounted(() => window.removeEventListener('keydown', keyboard))

async function save() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await submit(`/clips/${props.id}/update`, { ...fields })
    emit('saved')
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <q-banner v-if="editor.blocker" class="error-banner" role="alert">
    {{ editor.blocker.message }}
    <template v-if="editor.blocker.url" #action>
      <q-btn flat label="Otwórz odtwarzacz" :to="editor.blocker.url.replace('/videos/', '/recordings/')" />
    </template>
  </q-banner>
  <q-form v-else ref="form" class="q-gutter-sm" @submit="save">
    <q-banner v-if="error" class="error-banner" role="alert">{{ error }}</q-banner>
    <q-select v-model="fields.official" :options="officials" emit-value map-options outlined label="Sędzia" :rules="[required]" :disable="busy" />
    <q-select ref="category" v-model="fields.category_id" :options="editor.categories" emit-value map-options outlined label="Kategoria" :rules="[required]" :disable="busy" />
    <q-input v-if="custom" v-model="fields.custom_category" outlined label="Nazwa własnej kategorii" maxlength="100" :disable="busy" />
    <q-input ref="description" v-model="fields.description" outlined type="textarea" label="Opis" maxlength="2000" :disable="busy" />
    <q-btn type="submit" color="primary" label="Zapisz opis" :loading="busy" />
  </q-form>
</template>
