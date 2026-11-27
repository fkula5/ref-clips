<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppBrand from '../components/common/AppBrand.vue'
import ThemeToggle from '../components/common/ThemeToggle.vue'
import { useSession } from '../composables/useSession'
import { errorMessage } from '../api/client'

const session = useSession()
const route = useRoute()
const router = useRouter()
const email = ref('')
const password = ref('')
const showPassword = ref(false)
const busy = ref(false)
const error = ref('')
const requiredEmail = (value: string) => !!value.trim() || 'Podaj adres e-mail'
const requiredPassword = (value: string) => !!value || 'Podaj hasło'

async function login() {
  busy.value = true
  error.value = ''
  try {
    await session.login({ email: email.value, password: password.value })
    password.value = ''
    const next = route.query.next
    const target = typeof next === 'string' && next.startsWith('/') && !next.startsWith('//')
      ? router.resolve(next)
      : null
    if (target?.name && target.meta.requiresAuth && target.name !== 'not-found') {
      const hash = target.name === 'recording' && route.hash.startsWith('#room=') ? route.hash : target.hash
      await router.replace({ name: target.name, params: target.params, query: target.query, hash })
    } else {
      await router.replace({ name: 'matches' })
    }
  } catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}
</script>

<template>
  <main class="login-page">
    <section class="login-story">
      <AppBrand />
      <div>
        <p>Analiza nagrań meczowych i klipów sędziowskich.</p>
      </div>
    </section>
    <section class="login-form-wrap">
      <q-form class="login-form" @submit="login">
        <header class="auth-heading">
          <h1>Zaloguj się</h1>
          <ThemeToggle />
        </header>
        <q-banner v-if="error" class="error-banner" role="alert">{{ error }}</q-banner>
        <q-banner v-if="route.query.password === 'saved'" class="notice-success q-mb-md" role="status">Hasło zapisane. Możesz się zalogować.</q-banner>
        <q-input v-model="email" outlined label="Adres e-mail" type="email" autocomplete="username" :disable="busy" :rules="[requiredEmail]" />
        <q-input v-model="password" outlined label="Hasło" :type="showPassword ? 'text' : 'password'" autocomplete="current-password" :disable="busy" :rules="[requiredPassword]">
          <template #append>
            <q-btn flat round dense :icon="showPassword ? 'visibility_off' : 'visibility'" :aria-label="showPassword ? 'Ukryj hasło' : 'Pokaż hasło'" @click="showPassword = !showPassword" />
          </template>
        </q-input>
        <RouterLink class="forgot" :to="{ name: 'password-reset' }">Nie pamiętasz hasła?</RouterLink>
        <q-btn type="submit" color="primary" label="Zaloguj się" size="lg" unelevated :loading="busy" class="full-width" />
        <p class="account-note">Nie masz konta? Poproś administratora o zaproszenie.</p>
      </q-form>
    </section>
  </main>
</template>
