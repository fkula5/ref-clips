<script setup lang="ts">
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { errorMessage } from '../api/client'
import { fetchNotificationSettings } from '../api/notifications'
import type { NotificationSettings } from '../api/notifications'
import { useSession } from '../composables/useSession'

const session = useSession()
const settings = ref<NotificationSettings>()
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const controller = new AbortController()

async function load() {
  loading.value = true
  error.value = ''
  try {
    settings.value = await fetchNotificationSettings(controller.signal)
  } catch (err) {
    if (!controller.signal.aborted) error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

async function save(test = false) {
  if (!settings.value || busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    if (test) {
      const result = await session.submit<NotificationSettings>('/settings/notifications/test')
      notice.value = result.notice ?? 'Wysłano testowe podsumowanie.'
    } else {
      const fields = Object.fromEntries(settings.value.events.map(event => [event.key, event.enabled ? '1' : '']))
      await session.submit('/settings/notifications', { ...fields, digest_enabled: settings.value.digest_enabled ? '1' : '' })
      notice.value = 'Zapisano ustawienia powiadomień.'
    }
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    busy.value = false
  }
}

onMounted(load)
onBeforeUnmount(() => controller.abort())
</script>

<template>
  <q-page class="matches-page document-page">
    <q-btn flat color="primary" label="Wróć do powiadomień" :to="{ name: 'notifications' }" />
    <header class="page-heading q-mt-lg"><h1>Ustawienia powiadomień</h1></header>
    <LoadingSkeleton v-if="loading && !settings" variant="form" label="Ładowanie ustawień powiadomień" />
    <q-banner v-if="error" class="error-banner q-mb-md" role="alert">
      {{ error }}
      <template v-if="!settings" #action><q-btn flat label="Ponów" @click="load" /></template>
    </q-banner>
    <q-banner v-if="notice" class="notice-success q-mb-md" role="status">{{ notice }}</q-banner>
    <q-card v-if="settings" flat bordered>
      <q-card-section>
        <q-form @submit="save()">
          <q-toggle v-model="settings.digest_enabled" label="Wysyłaj codzienne podsumowanie e-mailem" :disable="busy" />
          <div class="column q-my-md">
            <q-checkbox v-for="event in settings.events" :key="event.key" v-model="event.enabled" :label="event.label" :disable="busy" />
          </div>
          <q-btn type="submit" color="primary" label="Zapisz ustawienia" :loading="busy" />
        </q-form>
      </q-card-section>
      <q-card-section v-if="settings.can_test">
        <p v-if="settings.mail_problem" class="muted">{{ settings.mail_problem }}</p>
        <q-btn flat label="Wyślij mi testowe podsumowanie" :disable="busy || Boolean(settings.mail_problem)" @click="save(true)" />
      </q-card-section>
    </q-card>
  </q-page>
</template>
