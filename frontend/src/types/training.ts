import type { SelectOption } from './api'

export interface NamedItem { id: number; name: string }
export interface CatalogItem extends NamedItem { description: string }
export interface GroupSummary extends CatalogItem {
  viewable: boolean
  pinned: (NamedItem & { clips: number })[]
}

export interface GroupList { items: GroupSummary[]; can_create: boolean }
export interface GroupDetail extends Omit<GroupSummary, 'viewable'> {
  can_manage: boolean
  days: number
  periods: number[]
  review_count: number
  activity: (NamedItem & { recordings: number; markers: number; described: number; last: string })[]
  coaches: NamedItem[]
  candidates: Record<'referee' | 'coach', SelectOption[]>
}

export interface GroupReview {
  group: CatalogItem
  page: number
  pages: number
  items: { id: number; match: string; time: string; category: string; official: string; description: string }[]
}

export interface SetInfo extends CatalogItem {
  show_names: boolean
  groups: NamedItem[]
}

export interface SetList {
  items: (SetInfo & { clips: number })[]
  page: number
  pages: number
  can_edit: boolean
}

export interface SetItem {
  id: number
  match: string
  level: string
  official: string
  category: string
  note: string
}

export interface SetDetail extends SetInfo {
  can_edit: boolean
  items: SetItem[]
  group_choices: SelectOption[]
}

export interface SetClip extends SetItem {
  can_edit: boolean
  set_id: number
  set_name: string
  index: number
  total: number
  previous: number | null
  next: number | null
  stream: string | null
  description: string
}
