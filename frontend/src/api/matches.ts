import { api, request } from './client'
import type { MatchDetail, MatchFilters, MatchFormData, MatchPage } from '../types/api'

export function fetchMatchForm(id: string | undefined, signal: AbortSignal) {
  const path = id ? `/matches/${encodeURIComponent(id)}/edit` : '/matches/new'
  return request<MatchFormData>(path, { signal })
}

export function fetchMatchDetail(id: string, page: string, signal: AbortSignal) {
  const query = new URLSearchParams({ page })
  return api<MatchDetail>(`/matches/${encodeURIComponent(id)}?${query}`, { signal })
}

export function fetchMatches(filters: MatchFilters, page: number, signal?: AbortSignal) {
  const query = new URLSearchParams({ page: String(page) })
  if (filters.level) query.set('level', filters.level)
  if (filters.person) query.set('person', filters.person)
  if (filters.group) query.set('group', filters.group)
  if (filters.mine) query.set('mine', '1')
  if (filters.dateFrom) query.set('date_from', filters.dateFrom)
  if (filters.dateTo) query.set('date_to', filters.dateTo)
  return api<MatchPage>(`/matches?${query}`, { signal })
}
