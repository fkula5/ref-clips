import type { SelectOption } from './api'

export interface Sheet {
  id: number
  match: { id: number; title: string }
  author: string
  published: boolean
  can_edit: boolean
  can_publish: boolean
  can_delete: boolean
  changes: string[]
  values: Record<string, string>
  difficulties: SelectOption[]
  columns: { id: number; label: string; overall: string; recommendation: string; fields: Field[] }[]
}

interface Field { key: string; label: string }

export interface AssessmentSummary {
  id: number
  title: string
  author: string
  published: boolean
  match_id: number | null
}

export interface AssessmentList {
  mine: AssessmentSummary[]
  submitted: AssessmentSummary[]
  page: number
  pages: number
  can_create: boolean
}

export interface Assessment extends AssessmentSummary {
  header: { level: string; date: string; team_a: string; team_b: string; main_referee: string; assistants: string }
  can_edit: boolean
  can_delete: boolean
  can_reopen: boolean
  league_names: string[]
  questions: Field[]
  header_fields: Field[]
  min_clips: number
  values: Record<string, string>
  rows: { id: number; clip_id: number | null; manual: boolean; name: string; time: string; hint: string | null; name_key: string; desc_key: string }[]
  available: { id: number; label: string }[]
}
