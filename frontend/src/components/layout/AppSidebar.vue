<script setup lang="ts">
import AppBrand from '../common/AppBrand.vue'
import { useSession } from '../../composables/useSession'
import type { UserRole } from '../../types/api'
import { primaryLinks, useNavigation } from './navigation'

defineProps<{ loggingOut: boolean }>()
defineEmits<{ logout: [] }>()
const { user } = useSession()
const { accountLinks, isActive } = useNavigation()
const roles: Record<UserRole, string> = { admin: 'Administrator', coach: 'Szkoleniowiec', referee: 'Sędzia' }
</script>

<template>
  <q-drawer :model-value="true" behavior="desktop" :width="248" class="sidebar">
    <nav class="sidebar-navigation" aria-label="Menu główne">
      <AppBrand />
      <p class="nav-label">TWOJA PRZESTRZEŃ</p>
      <q-list padding>
        <q-item
          v-for="link in primaryLinks" :key="link.name"
          clickable exact :to="{ name: link.name }"
          :active="isActive(link.name, link.children)" active-class="nav-active"
        >
          <q-item-section avatar><q-icon :name="link.icon" /></q-item-section>
          <q-item-section>{{ link.label }}</q-item-section>
        </q-item>
        <q-item
          v-for="link in accountLinks" :key="link.name"
          clickable exact :to="{ name: link.name, params: link.params }"
          :active="isActive(link.name, link.children)" active-class="nav-active"
        >
          <q-item-section avatar><q-icon :name="link.icon" /></q-item-section>
          <q-item-section>{{ link.label }}</q-item-section>
        </q-item>
      </q-list>
      <div class="sidebar-bottom">
        <div class="user-role">{{ user?.roles.map(role => roles[role]).join(' · ') }}</div>
        <q-btn flat icon="logout" label="Wyloguj się" :loading="loggingOut" @click="$emit('logout')" />
      </div>
    </nav>
  </q-drawer>
</template>

<style scoped>
.sidebar-navigation {
  display: flex;
  flex-direction: column;
  min-height: 100%;
}

.sidebar-bottom {
  position: static;
  margin: auto 20px 26px 24px;
}
</style>
