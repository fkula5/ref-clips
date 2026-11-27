export type UserRole = 'admin' | 'coach' | 'referee'

export interface User {
  id: number
  name: string
  email: string
  roles: UserRole[]
  can_create_match: boolean
  can_access_admin: boolean
  can_see_self_assessments: boolean
}

export interface CsrfResponse { csrf_token: string }
export interface SessionResponse extends CsrfResponse { user: User }
export interface LoginCredentials { email: string; password: string }

export interface MatchSummary {
  id: number
  date: string
  teams: string
  level: string
  officials: { function: string; name: string; user_id: number | null }[]
  state: { code: string; label: string; detail: string }
}

export interface Match extends MatchSummary {
  clips: number
  undescribed: number
}

export interface MatchRecording {
  id: number
  name: string
  status: string
  can_play: boolean
  purged: boolean
  can_edit: boolean
  can_retry: boolean
  can_delete: boolean
  problem: string | null
}

export interface MatchClip {
  id: number
  time: string
  category: string
  description: string
  described: boolean
  status: string
  status_key?: string
}

export interface ClipFeedback {
  id: number
  author: string
  date: string
  text: string
  can_edit: boolean
  can_delete: boolean
}

export interface SelectOption { value: string; label: string }
export interface ClipDescription {
  official: string
  category_id: string
  custom_category: string
  description: string
}

export interface ClipDetail extends MatchClip {
  match: { id: number; title: string }
  previous: { id: number; time: string } | null
  next: { id: number; time: string } | null
  period: string
  official: string
  unavailable: boolean
  cut_error: string | null
  can_recut: boolean
  pending: boolean
  adjust: { start: number; end: number; time: number; video_id: number; fps: number } | null
  can_delete: boolean
  sharing: {
    can_create: boolean
    days: number[]
    links: { id: number; expiry: string; views: number; can_revoke: boolean }[]
  } | null
  set_choices: { id: number; name: string; has_clip: boolean }[] | null
  stream_url: string | null
  recording_url: string | null
  editor: {
    values: ClipDescription
    blocker: { message: string; url: string | null } | null
    officials: SelectOption[]
    categories: (SelectOption & { custom: boolean })[]
  } | null
  can_rate: boolean
  verdicts: SelectOption[]
  ratings: (ClipFeedback & { verdict: string; verdict_key: string; mine: boolean })[]
  comments: ClipFeedback[]
  older_before: number | null
}

export interface ClipLibrary {
  items: (MatchClip & {
    match: { id: number; title: string }
    official: string
    period: string
    comments: number
    ratings: number
    shareable: boolean
    exportable: boolean
  })[]
  total: number
  page: number
  pages: number
  options: Record<string, SelectOption[]>
  share_days: number[]
  share_limit: number
  can_export: boolean
}

export interface MatchDetail extends MatchSummary {
  expiry: string | null
  can_edit: boolean
  can_delete: boolean
  can_upload: boolean
  can_describe: boolean
  pending: boolean
  documents: {
    can_start_sheet: boolean
    can_start_assessment: boolean
    sheets: MatchDocument[]
    assessments: MatchDocument[]
    protocol: {
      can_manage: boolean
      accept: string
      max_files: number
      max_bytes: number
      files: { id: number; name: string; size: number; inline: boolean }[]
    }
  }
  upload: {
    chunk_bytes: number
    max_bytes: number
    periods: string[]
    can_add_notes: boolean
    notes_max_chars: number
  } | null
  videos: MatchRecording[]
  clips: { items: MatchClip[]; total: number; page: number; pages: number }
}

export interface MatchDocument { id: number; author: string; published: boolean; can_edit: boolean }

export type CrewSlot = 'cc' | 'u1' | 'u2'
export type TeamSide = 'a' | 'b'
export type MatchFormValues = Record<
  'date' | 'level' | `team_${TeamSide}_${'name' | 'color'}` | `${CrewSlot}_${'user' | 'name'}`,
  string
>

export interface MatchFormData {
  values: MatchFormValues
  levels: string[]
  extra_level: string | null
  referees: SelectOption[]
}

export interface MatchPage {
  items: Match[]
  total: number
  page: number
  pages: number
  levels: string[]
  people: SelectOption[]
  groups: SelectOption[]
  errors: string[]
}

export interface MatchFilters {
  level: string | null
  person: string | null
  group: string | null
  mine: boolean
  dateFrom: string
  dateTo: string
}
