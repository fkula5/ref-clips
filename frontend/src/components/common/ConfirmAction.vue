<script setup lang="ts">
const open = defineModel<boolean>({ required: true })
defineProps<{ title: string; message: string; label: string; busy: boolean }>()
defineEmits<{ confirm: [] }>()
</script>

<template>
  <q-dialog v-model="open" :persistent="busy">
    <q-card>
      <q-card-section>
        <h2 class="text-h6 q-mb-sm">{{ title }}</h2>
        <p class="q-mb-none">{{ message }}</p>
      </q-card-section>
      <q-card-actions align="right">
        <q-btn flat label="Anuluj" :disable="busy" @click="open = false" />
        <q-btn color="negative" :label="label" :loading="busy" @click="$emit('confirm')" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>
