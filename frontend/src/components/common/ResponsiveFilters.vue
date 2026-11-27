<script setup lang="ts">
import { ref, useId } from 'vue'
import { useQuasar } from 'quasar'

const screen = useQuasar().screen
const expanded = ref(false)
const id = useId()
</script>

<template>
  <div class="responsive-filters">
    <q-btn v-if="screen.xs" flat color="primary" icon="tune"
      :label="expanded ? 'Ukryj filtry' : 'Pokaż filtry'"
      :aria-expanded="expanded" :aria-controls="id" @click="expanded = !expanded" />
    <div v-show="!screen.xs || expanded" :id="id">
      <slot :close="() => expanded = false" />
    </div>
  </div>
</template>
