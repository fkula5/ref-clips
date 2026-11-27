import { onScopeDispose, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { LocationQuery, LocationQueryRaw } from 'vue-router'
import { fetchMatches } from '../api/matches'
import { ApiError, errorMessage } from '../api/client'
import { useSession } from './useSession'
import type { MatchFilters, MatchPage } from '../types/api'

function queryString(query: LocationQuery, key: string): string {
  const value = query[key]
  return typeof value === 'string' ? value : ''
}

export function useMatches() {
  const route = useRoute()
  const router = useRouter()
  const session = useSession()
  const filters = reactive<MatchFilters>({ level: '', person: '', group: '', mine: false, dateFrom: '', dateTo: '' })
  const result = ref<MatchPage>({ items: [], total: 0, page: 1, pages: 1, levels: [], people: [], groups: [], errors: [] })
  const loading = ref(false)
  const error = ref('')
  let controller: AbortController | undefined

  async function load() {
    controller?.abort()
    const request = new AbortController()
    controller = request
    loading.value = true
    error.value = ''
    const rawPage = Number(queryString(route.query, 'page'))
    const page = Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1
    try {
      const data = await fetchMatches(filters, page, request.signal)
      if (!request.signal.aborted) result.value = data
    } catch (err) {
      if (request.signal.aborted) return
      if (err instanceof ApiError && err.status === 401) {
        session.clear()
        await router.replace({ name: 'login', query: { next: route.fullPath } })
      } else { error.value = errorMessage(err) }
    } finally {
      if (!request.signal.aborted) loading.value = false
    }
  }

  function queryFor(page: number): LocationQueryRaw {
    return {
      level: filters.level || undefined,
      person: filters.person || undefined,
      group: filters.group || undefined,
      mine: filters.mine ? '1' : undefined,
      date_from: filters.dateFrom || undefined,
      date_to: filters.dateTo || undefined,
      page: page > 1 ? String(page) : undefined,
    }
  }

  async function navigate(page: number) {
    const target = { name: 'matches', query: queryFor(page) }
    if (router.resolve(target).fullPath === route.fullPath) await load()
    else await router.push(target)
  }

  watch(() => route.query, query => {
    Object.assign(filters, {
      level: queryString(query, 'level'),
      person: queryString(query, 'person'),
      group: queryString(query, 'group'),
      mine: ['1', 'on', 'true'].includes(queryString(query, 'mine')),
      dateFrom: queryString(query, 'date_from'),
      dateTo: queryString(query, 'date_to'),
    })
    void load()
  }, { immediate: true })

  onScopeDispose(() => controller?.abort())
  return { filters, result, loading, error, refresh: load, applyFilters: () => navigate(1), changePage: navigate }
}
