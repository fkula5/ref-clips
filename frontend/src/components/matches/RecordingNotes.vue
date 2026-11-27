<script setup lang="ts">
import { ref } from 'vue'
import { errorMessage, request } from '../../api/client'
import { useSession } from '../../composables/useSession'
import type { SelectOption } from '../../types/api'

interface NoteRow {
  line_no: number
  raw: string
  clock: string
  official_id: number | null
  category: string | null
  description: string
  warnings: string[]
  in_range: boolean
}

interface Preview {
  rows: NoteRow[]
  officials: SelectOption[]
  categories: SelectOption[]
  category_ids: Record<string, string>
}

const props = defineProps<{ id: number }>()
const emit = defineEmits<{ saved: [] }>()
const { csrfHeaders, submit } = useSession()
const text = ref('')
const preview = ref<Preview | null>(null)
const drafts = ref<{ include: boolean; time: string; official: string; category: string; description: string }[]>([])
const error = ref('')
const status = ref('')
const busy = ref(false)

async function run(action: () => Promise<void>) {
  if (busy.value) return
  error.value = ''
  status.value = ''
  busy.value = true
  try {
    await action()
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    busy.value = false
  }
}

function parse() {
  return run(async () => {
    const data = await request<Preview>(`/api/videos/${props.id}/notes/preview`, {
      method: 'POST',
      headers: { ...await csrfHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text.value }),
    })
    drafts.value = data.rows.map(row => ({
      include: row.in_range, time: row.in_range ? row.clock : '',
      official: row.official_id ? String(row.official_id) : '',
      category: row.category ? data.category_ids[row.category] ?? '' : '',
      description: row.description,
    }))
    preview.value = data
  })
}

function save() {
  return run(async () => {
    const fields: Record<string, string> = { count: String(drafts.value.length) }
    drafts.value.forEach((draft, i) => {
      if (!draft.include) return
      fields[`include_${i}`] = '1'
      fields[`time_${i}`] = draft.time
      fields[`referee_${i}`] = draft.official
      fields[`category_${i}`] = draft.category
      fields[`desc_${i}`] = draft.description
    })
    const result = await submit<{ created: number; skipped: number }>(`/videos/${props.id}/notes/commit`, fields)
    status.value = `Dodano klipy (${result.created}). Pominięto zaznaczone wiersze (${result.skipped}).`
    preview.value = null
    if (!result.skipped) text.value = ''
    emit('saved')
  })
}
</script>

<template>
  <q-expansion-item label="Wklej notatki" icon="edit_note" class="q-mb-md">
    <q-card flat bordered>
      <q-card-section>
        <q-banner v-if="error" class="error-banner q-mb-sm" role="alert">{{ error }}</q-banner>
        <p v-if="status" role="status">{{ status }}</p>
        <q-input v-model="text" type="textarea" outlined label="Notatki" placeholder="2:54 Filip kroki" :disable="busy" @update:model-value="preview = null" />
        <q-btn outline color="primary" label="Sprawdź notatki" class="q-mt-sm" :disable="!text.trim()" :loading="busy" @click="parse" />
        <template v-if="preview">
          <p v-if="!preview.rows.length" class="muted q-mt-md">Brak wierszy do zaimportowania.</p>
          <q-card v-for="(draft, i) in drafts" :key="preview.rows[i].line_no" flat bordered class="q-my-md">
            <q-card-section>
              <q-checkbox v-model="draft.include" :label="`Dodaj wiersz ${preview.rows[i].line_no}`" :disable="busy" />
              <p>{{ preview.rows[i].raw }}</p>
              <p v-if="preview.rows[i].warnings.length" class="muted">{{ preview.rows[i].warnings.join(' · ') }}</p>
              <div class="row q-col-gutter-sm">
                <q-input v-model="draft.time" class="col-12 col-sm-2" outlined dense label="Czas" :disable="busy" />
                <q-select v-model="draft.official" class="col-12 col-sm-5" :options="preview.officials" outlined dense emit-value map-options label="Sędzia" :disable="busy" />
                <q-select v-model="draft.category" class="col-12 col-sm-5" :options="preview.categories" outlined dense emit-value map-options label="Kategoria" :disable="busy" />
                <q-input v-model="draft.description" class="col-12" outlined dense label="Opis" :disable="busy" />
              </div>
            </q-card-section>
          </q-card>
          <q-btn color="primary" label="Dodaj zaznaczone klipy" :disable="!drafts.some(draft => draft.include)" :loading="busy" @click="save" />
        </template>
      </q-card-section>
    </q-card>
  </q-expansion-item>
</template>
