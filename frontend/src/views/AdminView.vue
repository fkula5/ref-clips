<script setup lang="ts">
import LoadingSkeleton from '../components/common/LoadingSkeleton.vue'
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AdminDictionaries from '../components/admin/AdminDictionaries.vue'
import AdminRetention from '../components/admin/AdminRetention.vue'
import AdminUsers from '../components/admin/AdminUsers.vue'
import { useResource } from '../composables/useResource'

const route = useRoute()
const router = useRouter()
const { data, error, loading } = useResource<{ sections: { id: string; label: string }[] }>(() => '/admin')
const section = computed(() => data.value?.sections.find(item => item.id === route.params.section))

watch([data, () => route.params.section], ([info, current]) => {
  if (info?.sections.length && !current) {
    void router.replace({ name: 'administration', params: { section: info.sections[0].id } })
  }
})
</script>

<template>
  <q-page class="matches-page">
    <header class="page-heading"><h1>Administracja</h1></header>
    <LoadingSkeleton v-if="loading && !data" variant="detail" label="Ładowanie panelu administracyjnego" />
    <q-banner v-if="error" class="error-banner q-my-md" role="alert">{{ error }}</q-banner>
    <template v-if="data">
      <q-tabs align="left" active-color="primary" class="q-mb-lg">
        <q-route-tab v-for="item in data.sections" :key="item.id" :label="item.label" :to="{ name: 'administration', params: { section: item.id } }" />
      </q-tabs>
      <AdminUsers v-if="section?.id === 'users'" />
      <AdminRetention v-else-if="section?.id === 'retention'" />
      <AdminDictionaries v-else-if="section" :key="section.id" :kind="section.id" :title="section.label" />
      <q-banner v-else-if="route.params.section">Ta sekcja jest niedostępna.</q-banner>
    </template>
  </q-page>
</template>
