<script setup lang="ts">
import { useQuasar } from 'quasar'
import { saveThemePreference } from '../../theme'

const { dark } = useQuasar()

function toggleTheme() {
  dark.toggle()
  saveThemePreference(dark.isActive)
}
</script>

<template>
  <q-btn flat round class="theme-toggle" :icon="dark.isActive ? 'light_mode' : 'dark_mode'"
    aria-label="Tryb ciemny" :aria-pressed="dark.isActive"
    :title="dark.isActive ? 'Włącz jasny motyw' : 'Włącz ciemny motyw'"
    @click="toggleTheme" />
</template>

<style scoped>
.theme-toggle { min-width: 44px; min-height: 44px; }
</style>
