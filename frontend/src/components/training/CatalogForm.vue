<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{ name?: string; description?: string; showNames?: boolean; saving: boolean; submitLabel: string }>()
const emit = defineEmits<{ save: [values: Record<string, string>]; cancel: [] }>()
const name = ref(props.name ?? '')
const description = ref(props.description ?? '')
const showNames = ref(props.showNames ?? false)

function submit() {
  emit('save', { name: name.value, description: description.value, show_names: showNames.value ? '1' : '' })
}
</script>

<template>
  <q-form class="q-gutter-sm" @submit="submit">
    <q-input v-model="name" outlined label="Nazwa" maxlength="100" :disable="saving" :rules="[v => Boolean(v?.trim()) || 'Podaj nazwę.']" />
    <q-input v-model="description" outlined type="textarea" label="Opis" maxlength="1000" :disable="saving" />
    <q-checkbox v-if="props.showNames !== undefined" v-model="showNames" label="Pokazuj nazwiska sędziów w zestawie" :disable="saving" />
    <div class="row q-gutter-sm">
      <q-btn type="submit" color="primary" :label="submitLabel" :loading="saving" />
      <q-btn flat label="Anuluj" :disable="saving" @click="$emit('cancel')" />
    </div>
  </q-form>
</template>
