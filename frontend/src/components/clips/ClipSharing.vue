<script setup lang="ts">
import { computed, ref } from 'vue'
import { errorMessage } from '../../api/client'
import { useSession } from '../../composables/useSession'
import ConfirmAction from '../common/ConfirmAction.vue'
import type { ClipDetail } from '../../types/api'

const props = defineProps<{ id: number; sharing: NonNullable<ClipDetail['sharing']> }>()
const emit = defineEmits<{ saved: [] }>()
const { submit } = useSession()
const days = ref(props.sharing.days[0])
const url = ref('')
const busy = ref(false)
const error = ref('')
const revokeId = ref<number | null>(null)
const confirmOpen = computed({
  get: () => revokeId.value !== null,
  set: open => { if (!open) revokeId.value = null },
})

async function change(revoke: number | null = null) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    if (revoke === null) {
      const created = await submit<{ url: string }>('/share-links', { clip_ids: String(props.id), days: String(days.value) })
      url.value = created.url
    } else {
      await submit(`/share-links/${revoke}/revoke`)
      revokeId.value = null
    }
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
      <h2 class="text-h6 q-mb-sm">Udostępnij klip</h2>
      <p class="muted">Każdy posiadacz linku może obejrzeć klip bez logowania.</p>
      <q-banner v-if="error" class="error-banner" role="alert">{{ error }}</q-banner>
      <q-form v-if="sharing.can_create" class="row items-center q-gutter-sm" @submit="change()">
        <q-select v-model="days" :options="sharing.days" dense outlined label="Ważność (dni)" :disable="busy" />
        <q-btn type="submit" color="primary" label="Utwórz link" :loading="busy" />
      </q-form>
      <p v-else class="muted">Link można utworzyć po wycięciu klipu.</p>
      <q-input v-if="url" :model-value="url" outlined readonly label="Skopiuj utworzony link" class="q-mt-md" />
      <q-list v-if="sharing.links.length" separator class="q-mt-md">
        <q-item v-for="link in sharing.links" :key="link.id">
          <q-item-section>Ważny do {{ link.expiry }} · Wejścia {{ link.views }}</q-item-section>
          <q-item-section v-if="link.can_revoke" side>
            <q-btn flat color="negative" label="Unieważnij" :disable="busy" @click="revokeId = link.id" />
          </q-item-section>
        </q-item>
      </q-list>
    </q-card-section>
    <ConfirmAction v-model="confirmOpen" title="Unieważnić link?" message="Osoby korzystające z linku stracą dostęp do klipu." label="Unieważnij" :busy="busy" @confirm="change(revokeId)" />
  </q-card>
</template>
