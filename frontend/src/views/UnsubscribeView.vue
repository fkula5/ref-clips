<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { errorMessage, request } from '../api/client'
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'

type State = { state: 'confirm' | 'done' }
const route = useRoute()
const path = computed(() => `/unsubscribe/${encodeURIComponent(String(route.params.token))}`)
const state = ref<State>()
const error = ref('')
const busy = ref(false)

async function load(method: 'GET' | 'POST') {
  busy.value = true
  error.value = ''
  try {
    state.value = await request<State>(path.value, { method, credentials: 'omit' })
  } catch (err) {
    error.value = method === 'GET' ? 'Ten link jest nieprawidłowy.' : errorMessage(err)
  } finally {
    busy.value = false
  }
}

watch(path, () => { void load('GET') }, { immediate: true })
</script>

<template>
  <main class="login-form-wrap standalone-auth">
    <div class="login-form">
      <h1 class="text-h4">Podsumowania e-mail</h1>
      <LoadingSkeleton v-if="busy && !state" variant="inline" label="Sprawdzanie linku do wypisania" />
      <q-banner v-if="error" class="error-banner q-my-md" role="alert">{{ error }}</q-banner>
      <p v-if="state?.state === 'done'" role="status">Podsumowania e-mail są wyłączone.</p>
      <q-btn v-if="state?.state === 'confirm'" color="primary" label="Wypisz z podsumowań" :loading="busy" @click="load('POST')" />
    </div>
  </main>
</template>

<style scoped>
.standalone-auth { min-height: 100vh; }
</style>
