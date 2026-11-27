import { request } from './client'

interface RecordingMark { id: number; time_sec: number; clock: string }
export interface RecordingClip extends RecordingMark {
  period: string | null
  period_clock: string | null
  official: string | null
  category: string | null
  status: 'new' | 'queued' | 'cut' | 'error'
  error: string | null
  described: boolean
  can_delete: boolean
  clip_start: number
  clip_end: number
}

export interface RecordingState {
  video_id: number
  name: string
  match_id: number
  match_title: string
  playable: boolean
  can_mark: boolean
  can_clip: boolean
  quick_cut: { before: number; after: number }
  can_download: boolean
  single_period: boolean
  duration: number | null
  fps: number
  content_label: string
  periods: { period: string; required: boolean; mark: RecordingMark | null }[]
  missing_periods: string[]
  next_period: string | null
  clip_id?: number
  warnings?: string[]
  marker?: RecordingMark
  created?: boolean
  clip?: RecordingMark
  period?: string
  clips: RecordingClip[]
}

export function fetchRecording(id: string, signal: AbortSignal) {
  return request<RecordingState>(`/api/videos/${encodeURIComponent(id)}/state`, { signal })
}

export function updateRecording(path: string, headers: HeadersInit, payload?: object, method = 'POST') {
  const requestHeaders = new Headers(headers)
  if (payload) requestHeaders.set('Content-Type', 'application/json')
  return request<RecordingState>(path, {
    method, headers: requestHeaders, body: payload ? JSON.stringify(payload) : undefined,
  })
}
