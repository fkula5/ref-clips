<script setup lang="ts">
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchCsrf } from '../api/auth'
import { errorMessage, request } from '../api/client'
import { useResource } from '../composables/useResource'
import { useSession } from '../composables/useSession'

const route = useRoute()
const router = useRouter()
const { data, loading, error } = useResource<{ email: string; name: string; purpose: string }>(() => `/set-password/${encodeURIComponent(String(route.params.token))}`)
const password = ref('')
const repeat = ref('')
const saving = ref(false)
const formError = ref('')

async function save() {
  if (saving.value) return
  saving.value = true
  formError.value = ''
  try {
    const { csrf_token } = await fetchCsrf()
    await request(`/set-password/${encodeURIComponent(String(route.params.token))}`, {
      method: 'POST', headers: { 'X-CSRF-Token': csrf_token },
      body: new URLSearchParams({ password: password.value, password2: repeat.value }),
    })
    useSession().clear()
    await router.replace({ name: 'login', query: { password: 'saved' } })
  } catch (err) {
    formError.value = errorMessage(err)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <main class="login-form-wrap standalone-auth">
    <div class="login-form">
      <h1 class="text-h4">Ustaw hasło</h1>
      <LoadingSkeleton v-if="loading && !data" variant="form" label="Sprawdzanie linku do ustawienia hasła" :rows="2" />
      <q-banner v-if="error || formError" class="error-banner q-my-md" role="alert">{{ error || formError }}</q-banner>
      <q-form v-if="data" class="q-gutter-sm" @submit="save">
        <p>{{ data.name }} · {{ data.email }} · {{ data.purpose }}</p>
        <q-input v-model="password" outlined type="password" autocomplete="new-password" label="Nowe hasło" :rules="[v => (v?.length ?? 0) >= 10 || 'Podaj co najmniej 10 znaków.']" />
        <q-input v-model="repeat" outlined type="password" autocomplete="new-password" label="Powtórz hasło" :rules="[v => v === password || 'Hasła muszą być takie same.']" />
        <q-btn type="submit" color="primary" label="Zapisz hasło" :loading="saving" />
      </q-form>
      <q-btn flat color="primary" class="q-mt-md" label="Wróć do logowania" :to="{ name: 'login' }" />
    </div>
  </main>
</template>

<style scoped>
.standalone-auth { min-height: 100vh; }
</style>
