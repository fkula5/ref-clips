<script setup lang="ts">
import { ref } from 'vue'
import { errorMessage, request } from '../api/client'
import { fetchCsrf } from '../api/auth'

const email = ref('')
const contact = ref('')
const error = ref('')
const busy = ref(false)
const minutes = ref<number>()

async function send() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const { csrf_token } = await fetchCsrf()
    const result = await request<{ minutes: number }>('/forgot-password', {
      method: 'POST', headers: { 'X-CSRF-Token': csrf_token },
      body: new URLSearchParams({ email: email.value, contact_url: contact.value }),
    })
    minutes.value = result.minutes
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="login-form-wrap standalone-auth">
    <div class="login-form">
      <h1 class="text-h4">Odzyskaj hasło</h1>
      <q-banner v-if="error" class="error-banner q-my-md" role="alert">{{ error }}</q-banner>
      <q-banner v-if="minutes" class="notice-success q-my-md" role="status">
        Jeśli konto o podanym adresie istnieje, link do ustawienia hasła został wysłany. Jest ważny przez {{ minutes }} minut.
      </q-banner>
      <q-form v-else class="q-gutter-sm" @submit="send">
        <q-input v-model="email" outlined type="email" autocomplete="email" label="Adres e-mail" maxlength="255" :rules="[v => Boolean(v?.trim()) || 'Podaj e-mail.']" />
        <div class="reset-trap" aria-hidden="true"><label>Nie wypełniaj <input v-model="contact" tabindex="-1" autocomplete="off"></label></div>
        <q-btn type="submit" color="primary" label="Wyślij link" :loading="busy" />
      </q-form>
      <q-btn flat color="primary" class="q-mt-md" label="Wróć do logowania" :to="{ name: 'login' }" />
    </div>
  </main>
</template>

<style scoped>
.standalone-auth { min-height: 100vh; }
.reset-trap { position: absolute; left: -10000px; }
</style>
