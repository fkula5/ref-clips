import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useSession } from '../../composables/useSession'

export const primaryLinks = [
  { name: 'matches', label: 'Mecze', icon: 'sports_basketball', children: ['match-detail', 'match-create', 'match-edit', 'recording', 'recording-edit', 'describe-queue', 'sheet'] },
  { name: 'clips', label: 'Klipy', icon: 'movie', children: ['clip-detail'] },
  { name: 'groups', label: 'Grupy szkoleniowe', icon: 'groups', children: ['group-detail', 'group-review'] },
  { name: 'sets', label: 'Zestawy szkoleniowe', icon: 'video_library', children: ['set-detail', 'set-clip'] },
]

export function useNavigation() {
  const route = useRoute()
  const { user } = useSession()
  function isActive(name: string, children: string[] = []) {
    if (name === 'referee') return route.name === name && route.params.id === String(user.value?.id)
    return route.name === name || (typeof route.name === 'string' && children.includes(route.name))
  }

  const accountLinks = computed(() => [
    { name: 'administration', label: 'Administracja', icon: 'admin_panel_settings', visible: user.value?.can_access_admin },
    { name: 'self-assessments', label: 'Samooceny', icon: 'assignment', children: ['self-assessment'], visible: user.value?.can_see_self_assessments },
    { name: 'referee', label: 'Mój profil', icon: 'person', params: { id: user.value?.id }, visible: user.value?.roles.includes('referee') },
  ].filter(link => link.visible))

  return { accountLinks, isActive }
}
