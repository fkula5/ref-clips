<script setup lang="ts">
import LoadingSkeleton from '../common/LoadingSkeleton.vue'
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useResource } from '../../composables/useResource'
import { useSession } from '../../composables/useSession'
import type { SelectOption } from '../../types/api'
import ConfirmAction from '../common/ConfirmAction.vue'

interface Account { id: number; name: string; email: string; roles: string[]; active: boolean; has_password: boolean }
const router = useRouter()
const session = useSession()
const { data, error, loading, saving, refresh, save } = useResource<{ items: Account[]; roles: SelectOption[]; invite: string | null }>(() => '/admin/users')
const name = ref('')
const email = ref('')
const roles = ref(['referee'])
const editing = ref<Account>()
const selected = ref<string[]>([])
const invite = ref('')
const notice = ref('')
const confirmation = ref(false)
const pending = ref<Account>()

watch(data, page => { if (page?.invite) invite.value = page.invite })

function fields(values: Record<string, string>, selectedRoles: string[]) {
  const payload = new URLSearchParams(values)
  selectedRoles.forEach(role => payload.append('roles', role))
  return payload
}

async function create() {
  const result = await save<{ invite: string }>('/admin/users', fields({ name: name.value, email: email.value }, roles.value))
  if (!result) return
  invite.value = result.invite
  name.value = ''
  email.value = ''
  roles.value = ['referee']
  refresh()
}

async function updateRoles() {
  const user = editing.value
  if (!user) return
  const result = await save<{ target: string; notice: string }>(`/admin/users/${user.id}/roles`, fields({}, selected.value))
  if (!result) return
  editing.value = undefined
  if (user.id === session.user.value?.id) {
    session.clear()
    await session.initialize()
  }
  if (result.target === '/') await router.replace({ name: 'matches' })
  else { notice.value = result.notice; refresh() }
}

async function setActive(user: Account) {
  const result = await save<{ notice: string }>(`/admin/users/${user.id}/active`, { active: user.active ? '0' : '1' })
  confirmation.value = false
  if (result) { notice.value = result.notice; refresh() }
}

async function createInvite(user: Account) {
  const result = await save<{ invite: string }>(`/admin/users/${user.id}/invite`)
  if (result) invite.value = result.invite
}
</script>

<template>
  <section>
    <h2 class="text-h5 q-mb-md">Użytkownicy</h2>
    <LoadingSkeleton v-if="loading && !data" variant="form" label="Ładowanie użytkowników" />
    <q-banner v-if="error" class="error-banner q-my-md" role="alert">{{ error }}</q-banner>
    <q-banner v-if="notice" class="notice-success q-my-md" role="status">{{ notice }}</q-banner>
    <q-input v-if="invite" :model-value="invite" readonly outlined label="Skopiuj link do ustawienia hasła" class="q-my-md" />
    <template v-if="data">
      <q-card flat bordered class="q-mb-lg">
        <q-card-section>
          <h3 class="text-h6">Dodaj konto</h3>
          <q-form class="q-gutter-sm" @submit="create">
            <q-input v-model="name" outlined label="Imię i nazwisko" maxlength="100" :rules="[v => Boolean(v?.trim()) || 'Podaj imię i nazwisko.']" />
            <q-input v-model="email" outlined type="email" label="E-mail" maxlength="255" :rules="[v => Boolean(v?.trim()) || 'Podaj e-mail.']" />
            <q-select v-model="roles" :options="data.roles" outlined multiple use-chips emit-value map-options label="Role" />
            <q-btn type="submit" color="primary" label="Utwórz konto i link" :loading="saving" :disable="!roles.length" />
          </q-form>
        </q-card-section>
      </q-card>
      <q-list bordered separator class="surface-panel rounded-borders">
        <q-item v-for="user in data.items" :key="user.id">
          <q-item-section>
            <q-item-label>{{ user.name }} · {{ user.active ? 'Aktywne' : 'Nieaktywne' }}</q-item-label>
            <q-item-label caption>{{ user.email }} · {{ user.roles.map(role => data?.roles.find(option => option.value === role)?.label ?? role).join(', ') }}</q-item-label>
            <q-form v-if="editing?.id === user.id" class="q-gutter-sm q-mt-sm" @submit="updateRoles">
              <q-select v-model="selected" :options="data.roles" outlined multiple use-chips emit-value map-options label="Role użytkownika" />
              <q-btn type="submit" color="primary" label="Zapisz role" :loading="saving" :disable="!selected.length" />
              <q-btn flat label="Anuluj" @click="editing = undefined" />
            </q-form>
            <div v-else class="row q-gutter-xs q-mt-sm">
              <q-btn flat dense label="Edytuj role" :disable="saving" @click="editing = user; selected = [...user.roles]" />
              <q-btn v-if="user.active" flat dense color="primary" :label="user.has_password ? 'Utwórz link resetu' : 'Utwórz link aktywacji'" :disable="saving" @click="createInvite(user)" />
              <q-btn v-if="user.active" flat dense color="negative" label="Dezaktywuj" :disable="saving" @click="pending = user; confirmation = true" />
              <q-btn v-else flat dense label="Aktywuj" :disable="saving" @click="setActive(user)" />
            </div>
          </q-item-section>
        </q-item>
      </q-list>
    </template>
    <ConfirmAction v-if="pending" v-model="confirmation" title="Dezaktywować konto?" :message="pending.name" label="Dezaktywuj" :busy="saving" @confirm="setActive(pending)" />
  </section>
</template>
