<script setup lang="ts">
import { ref } from 'vue'
import { useQuasar } from 'quasar'
import { useRouter } from 'vue-router'
import AppHeader from '../components/layout/AppHeader.vue'
import AppMobileNavigation from '../components/layout/AppMobileNavigation.vue'
import AppSidebar from '../components/layout/AppSidebar.vue'
import { useSession } from '../composables/useSession'
import { errorMessage } from '../api/client'

const router = useRouter()
const $q = useQuasar()
const session = useSession()
const loggingOut = ref(false)
const error = ref('')

async function logout() {
  loggingOut.value = true
  error.value = ''
  try {
    await session.logout()
    await router.replace({ name: 'login' })
  } catch (err) { error.value = errorMessage(err) }
  finally { loggingOut.value = false }
}
</script>

<template>
  <q-layout view="lHh Lpr lFf" class="workspace">
    <AppHeader>
      <template #mobile-navigation>
        <AppMobileNavigation v-if="$q.screen.lt.md" :logging-out="loggingOut" @logout="logout" />
      </template>
    </AppHeader>
    <AppSidebar v-if="!$q.screen.lt.md" :logging-out="loggingOut" @logout="logout" />
    <q-page-container>
      <q-banner v-if="error" class="error-banner q-ma-md" role="alert">{{ error }}</q-banner>
      <RouterView />
    </q-page-container>
  </q-layout>
</template>
