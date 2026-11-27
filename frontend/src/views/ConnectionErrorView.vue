<script setup lang="ts">
import { useRouter } from 'vue-router'
const router = useRouter()
</script>

<template>
  <main class="startup">
    <q-icon name="cloud_off" size="42px" />
    <h1>Nie udało się połączyć</h1>
    <p>Sprawdź połączenie i upewnij się, że backend działa.</p>
    <q-btn color="primary" label="Spróbuj ponownie" @click="router.replace({ name: 'matches' })" />
  </main>
</template>
