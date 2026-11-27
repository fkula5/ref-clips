import type { ClipDetail, ClipLibrary } from '../types/api'
import { api } from './client'

export function fetchClip(id: string, signal?: AbortSignal, filters = new URLSearchParams()) {
  return api<ClipDetail>(`/clips/${encodeURIComponent(id)}?${filters}`, { signal })
}

export function fetchLibrary(query: URLSearchParams, signal: AbortSignal) {
  return api<ClipLibrary>(`/clips?${query}`, { signal })
}
