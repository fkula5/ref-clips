<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { errorMessage, request } from '../../api/client'
import { useSession } from '../../composables/useSession'
import type { ClipDetail, ClipFeedback } from '../../types/api'

const props = defineProps<{ clip: ClipDetail }>()
const emit = defineEmits<{ saved: [] }>()
const { submit } = useSession()
const base = computed(() => `/clips/${props.clip.id}`)
const ratingId = ref<number | null>(null)
const commentId = ref<number | null>(null)
const verdict = ref('')
const ratingText = ref('')
const commentText = ref('')
const busy = ref(false)
const error = ref('')
const olderComments = ref<ClipFeedback[]>([])
const cursor = ref<number | null>(null)
const pendingDelete = ref<{ path: string; label: string } | null>(null)
const comments = computed(() => [...olderComments.value, ...props.clip.comments])

watch(() => props.clip.comments, () => {
  olderComments.value = []
  cursor.value = props.clip.older_before
}, { immediate: true })

function editRating(rating: ClipDetail['ratings'][number]) {
  ratingId.value = rating.id
  verdict.value = rating.verdict_key
  ratingText.value = rating.text
}

function editComment(comment: ClipFeedback) {
  commentId.value = comment.id
  commentText.value = comment.text
}

async function run(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await action()
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    busy.value = false
  }
}

function saveRating() {
  const path = ratingId.value === null ? '/rating' : `/ratings/${ratingId.value}/edit`
  return run(async () => {
    await submit(base.value + path, { verdict: verdict.value, comment: ratingText.value })
    ratingId.value = null
    verdict.value = ''
    ratingText.value = ''
    emit('saved')
  })
}

function saveComment() {
  const path = commentId.value === null ? '/comments' : `/comments/${commentId.value}/edit`
  return run(async () => {
    await submit(base.value + path, { body: commentText.value })
    commentId.value = null
    commentText.value = ''
    emit('saved')
  })
}

function deleteItem() {
  const item = pendingDelete.value
  if (!item) return
  return run(async () => {
    await submit(base.value + item.path)
    pendingDelete.value = null
    emit('saved')
  })
}

function loadOlder() {
  const before = cursor.value
  if (before === null) return
  return run(async () => {
    const page = await request<{ items: ClipFeedback[]; older_before: number | null }>(
      `${base.value}/comments?before=${before}`,
    )
    olderComments.value = [...page.items, ...olderComments.value]
    cursor.value = page.older_before
  })
}
</script>

<template>
  <q-card flat bordered>
    <q-banner v-if="error" class="error-banner q-ma-md" role="alert">{{ error }}</q-banner>
    <q-card-section id="oceny">
      <h2 class="text-h6 q-mb-md">Oceny szkoleniowców</h2>
      <p v-if="!clip.ratings.length" class="muted q-mb-none">Brak ocen.</p>
      <q-list v-else separator>
        <q-item v-for="rating in clip.ratings" :key="rating.id" class="q-px-none">
          <q-item-section>
            <q-item-label><q-badge class="state-badge" :data-status="rating.verdict_key" :label="rating.verdict" /> <span class="info-person">{{ rating.author }}</span></q-item-label>
            <q-item-label caption class="info-context">{{ rating.date }}</q-item-label>
            <q-item-label v-if="rating.text" class="feedback-text info-copy">{{ rating.text }}</q-item-label>
            <div v-if="rating.can_edit || rating.can_delete" class="row q-gutter-xs">
              <q-btn v-if="rating.can_edit" flat dense label="Edytuj ocenę" :disable="busy" @click="editRating(rating)" />
              <q-btn v-if="rating.can_delete" flat dense color="negative" label="Usuń ocenę" :disable="busy" @click="pendingDelete = { path: `/ratings/${rating.id}/delete`, label: 'Usunąć ocenę?' }" />
            </div>
          </q-item-section>
        </q-item>
      </q-list>
      <q-form v-if="ratingId !== null || (clip.can_rate && !clip.ratings.some(rating => rating.mine))" class="q-gutter-sm q-mt-md" @submit="saveRating">
        <q-select v-model="verdict" :options="clip.verdicts" emit-value map-options outlined label="Ocena" :disable="busy" :rules="[v => Boolean(v) || 'Wybierz ocenę.']" />
        <q-input v-model="ratingText" outlined type="textarea" label="Uzasadnienie oceny" :disable="busy" />
        <q-btn type="submit" color="primary" label="Zapisz ocenę" :loading="busy" />
        <q-btn v-if="ratingId !== null" flat label="Anuluj" :disable="busy" @click="ratingId = null; verdict = ''; ratingText = ''" />
      </q-form>
    </q-card-section>
    <q-separator />
    <q-card-section id="komentarze">
      <h2 class="text-h6 q-mb-md">Komentarze</h2>
      <q-btn v-if="cursor !== null" flat color="primary" label="Pokaż starsze komentarze" :loading="busy" @click="loadOlder" />
      <p v-if="!comments.length" class="muted q-mb-none">Brak komentarzy.</p>
      <q-list v-else separator>
        <q-item v-for="comment in comments" :key="comment.id" class="q-px-none">
          <q-item-section>
            <q-item-label class="info-person">{{ comment.author }}</q-item-label>
            <q-item-label caption class="info-context">{{ comment.date }}</q-item-label>
            <q-item-label class="feedback-text info-copy">{{ comment.text }}</q-item-label>
            <div v-if="comment.can_edit || comment.can_delete" class="row q-gutter-xs">
              <q-btn v-if="comment.can_edit" flat dense label="Edytuj komentarz" :disable="busy" @click="editComment(comment)" />
              <q-btn v-if="comment.can_delete" flat dense color="negative" label="Usuń komentarz" :disable="busy" @click="pendingDelete = { path: `/comments/${comment.id}/delete`, label: 'Usunąć komentarz?' }" />
            </div>
          </q-item-section>
        </q-item>
      </q-list>
      <q-form class="q-gutter-sm q-mt-md" @submit="saveComment">
        <q-input v-model="commentText" outlined type="textarea" :label="commentId === null ? 'Dodaj komentarz' : 'Edytuj komentarz'" :disable="busy" :rules="[v => Boolean(v?.trim()) || 'Wpisz komentarz.']" />
        <q-btn type="submit" color="primary" label="Zapisz komentarz" :loading="busy" />
        <q-btn v-if="commentId !== null" flat label="Anuluj" :disable="busy" @click="commentId = null; commentText = ''" />
      </q-form>
    </q-card-section>
    <q-dialog :model-value="pendingDelete !== null" :persistent="busy" @hide="pendingDelete = null">
      <q-card>
        <q-card-section>{{ pendingDelete?.label }}</q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Anuluj" :disable="busy" @click="pendingDelete = null" />
          <q-btn flat color="negative" label="Usuń" :loading="busy" @click="deleteItem" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-card>
</template>

<style scoped>
.feedback-text {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
