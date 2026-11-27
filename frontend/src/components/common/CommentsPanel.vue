<script setup lang="ts">
import LoadingSkeleton from './LoadingSkeleton.vue'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { request } from '../../api/client'
import { useResource } from '../../composables/useResource'
import type { ClipFeedback } from '../../types/api'
import ConfirmAction from './ConfirmAction.vue'

interface CommentPage { items: ClipFeedback[]; older_before: number | null }
const props = defineProps<{ base: string }>()
const route = useRoute()
const { data, error, loading, saving, refresh, save } = useResource<CommentPage>(() => `${props.base}/comments`)
const older = ref<ClipFeedback[]>([])
const cursor = ref<number | null>(null)
const pending = ref<ClipFeedback>()
const deleting = ref(false)
const formId = ref<number>()
const text = ref('')
const form = ref<HTMLElement>()
const loadingOlder = ref(false)
const olderError = ref('')
const comments = computed(() => [...older.value, ...(data.value?.items ?? [])])

watch(data, current => {
  older.value = []
  cursor.value = current?.older_before ?? null
  olderError.value = ''
})

async function change() {
  const action = formId.value ? `/${formId.value}/edit` : ''
  const result = await save(`${props.base}/comments${action}`, { body: text.value })
  if (result === undefined) return
  formId.value = undefined
  text.value = ''
  refresh()
}

async function remove() {
  if (!pending.value) return
  const result = await save(`${props.base}/comments/${pending.value.id}/delete`)
  deleting.value = false
  if (result !== undefined) refresh()
}

async function loadOlder() {
  if (loadingOlder.value || cursor.value === null) return
  loadingOlder.value = true
  olderError.value = ''
  try {
    const result = await request<CommentPage>(`${props.base}/comments?before=${cursor.value}`)
    older.value = [...result.items, ...older.value]
    cursor.value = result.older_before
  } catch {
    olderError.value = 'Nie udało się pobrać starszych komentarzy.'
  } finally {
    loadingOlder.value = false
  }
}

onMounted(() => {
  if (route.hash === '#komentarze') form.value?.closest('section')?.scrollIntoView()
})
</script>

<template>
  <section id="komentarze" aria-labelledby="match-comments-title">
    <h2 id="match-comments-title" class="text-h6">Komentarze do meczu</h2>
    <LoadingSkeleton v-if="loading && !data" variant="list" label="Ładowanie komentarzy" :rows="2" />
    <q-banner v-if="error || olderError" class="error-banner q-my-md" role="alert">{{ error || olderError }}</q-banner>
    <q-btn v-if="cursor !== null" flat color="primary" label="Pokaż starsze komentarze" :loading="loadingOlder" @click="loadOlder" />
    <p v-if="data && !comments.length" class="muted">Brak komentarzy.</p>
    <q-list v-else separator>
      <q-item v-for="comment in comments" :key="comment.id" class="q-px-none">
        <q-item-section>
          <q-item-label>{{ comment.author }} · {{ comment.date }}</q-item-label>
          <q-item-label class="comment-text">{{ comment.text }}</q-item-label>
          <div class="row q-gutter-xs q-mt-xs">
            <q-btn v-if="comment.can_edit" flat dense label="Edytuj" @click="formId = comment.id; text = comment.text; form?.scrollIntoView()" />
            <q-btn v-if="comment.can_delete" flat dense color="negative" label="Usuń" @click="pending = comment; deleting = true" />
          </div>
        </q-item-section>
      </q-item>
    </q-list>
    <div ref="form">
      <q-form v-if="data" class="q-gutter-sm q-mt-md" @submit="change">
        <q-input v-model="text" outlined type="textarea" :label="formId ? 'Edytuj komentarz' : 'Dodaj komentarz'" :disable="saving" :rules="[v => Boolean(v?.trim()) || 'Wpisz komentarz.']" />
        <q-btn type="submit" color="primary" label="Zapisz komentarz" :loading="saving" />
        <q-btn v-if="formId" flat label="Anuluj" @click="formId = undefined; text = ''" />
      </q-form>
    </div>
    <ConfirmAction v-if="pending" v-model="deleting" title="Usunąć komentarz?" :message="pending.author" label="Usuń komentarz" :busy="saving" @confirm="remove" />
  </section>
</template>

<style scoped>
.comment-text { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
