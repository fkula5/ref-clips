<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { request } from '../../api/client'
import { useSession } from '../../composables/useSession'
import AppBrand from '../common/AppBrand.vue'
import ThemeToggle from '../common/ThemeToggle.vue'

const { user } = useSession()
const router = useRouter()
const unread = ref(0)
const initials = computed(() => user.value?.name.split(/\s+/).map(n => n[0]).slice(0, 2).join(''))

async function updateUnread() {
  try {
    unread.value = (await request<{ unread: number }>('/notifications/bell')).unread
  } catch {
    // Keep the last count when the connection is interrupted.
  }
}

const removeHook = router.afterEach(() => { void updateUnread() })
let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  void updateUnread()
  timer = setInterval(updateUnread, 60_000)
})
onUnmounted(() => {
  removeHook()
  clearInterval(timer)
})
</script>

<template>
  <q-header class="app-header">
    <q-toolbar>
      <slot name="mobile-navigation" />
      <AppBrand class="lt-md" />
      <span class="toolbar-label gt-sm">Przestrzeń sędziego</span>
      <q-space />
      <ThemeToggle />
      <q-btn flat round icon="notifications" :aria-label="unread ? `Powiadomienia, nieprzeczytane: ${unread}` : 'Powiadomienia'" :to="{ name: 'notifications' }">
        <q-badge v-if="unread" color="negative" floating :label="unread > 99 ? '99+' : unread" />
      </q-btn>
      <span class="header-name gt-xs">{{ user?.name }}</span>
      <q-avatar color="primary" text-color="white" size="36px">{{ initials }}</q-avatar>
    </q-toolbar>
  </q-header>
</template>
