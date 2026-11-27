<script setup lang="ts">
import { useRoute } from 'vue-router'
import LoadingSkeleton from './components/common/LoadingSkeleton.vue'

const route = useRoute()
</script>

<template>
  <main v-if="!route.matched.length" class="matches-page">
    <LoadingSkeleton variant="detail" label="Ładowanie Ref Clips" />
  </main>
  <RouterView v-else />
</template>
