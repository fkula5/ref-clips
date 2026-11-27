<script setup lang="ts">
import { ref, useId } from 'vue'
import { primaryLinks, useNavigation } from './navigation'

defineProps<{ loggingOut: boolean }>()
defineEmits<{ logout: [] }>()
const { accountLinks, isActive } = useNavigation()
const open = ref(false)
const menuId = useId()
</script>

<template>
  <q-btn
    flat round icon="menu" class="mobile-menu-trigger"
    :aria-label="open ? 'Zamknij menu główne' : 'Otwórz menu główne'"
    aria-haspopup="dialog" :aria-expanded="open" :aria-controls="open ? menuId : undefined"
  >
    <q-menu v-model="open" :id="menuId" role="dialog" aria-label="Menu główne"
      class="mobile-menu" anchor="bottom left" self="top left" :offset="[0, 6]" max-height="calc(100dvh - 72px)">
      <nav aria-label="Menu główne">
        <q-list class="q-py-xs">
          <q-item v-for="link in primaryLinks" :key="link.name" v-close-popup clickable exact
            :to="{ name: link.name }" :active="isActive(link.name, link.children)" active-class="mobile-menu-active">
            <q-item-section avatar><q-icon :name="link.icon" /></q-item-section>
            <q-item-section>{{ link.label }}</q-item-section>
          </q-item>
          <q-separator spaced />
          <q-item v-for="link in accountLinks" :key="link.name" v-close-popup clickable exact
            :to="{ name: link.name, params: link.params }" :active="isActive(link.name, link.children)" active-class="mobile-menu-active">
            <q-item-section avatar><q-icon :name="link.icon" /></q-item-section>
            <q-item-section>{{ link.label }}</q-item-section>
          </q-item>
          <q-item v-close-popup clickable :disable="loggingOut" @click="$emit('logout')">
            <q-item-section avatar><q-icon name="logout" /></q-item-section>
            <q-item-section>Wyloguj się</q-item-section>
          </q-item>
        </q-list>
      </nav>
    </q-menu>
  </q-btn>
</template>

<style scoped>
.mobile-menu-trigger { min-width: 44px; min-height: 44px; }

.mobile-menu {
  width: min(270px, calc(100vw - 24px));
  color: var(--text-body);
}

.mobile-menu .q-list { padding-inline: 6px; }
.mobile-menu .q-item { min-height: 44px; border-radius: var(--radius-small); }
.mobile-menu .q-item__section--avatar { min-width: 38px; }

.mobile-menu-active {
  background: var(--surface-accent);
  color: var(--text-link);
  font-weight: 700;
}
</style>
