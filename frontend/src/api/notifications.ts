import { request } from './client'

export interface NotificationPage {
  items: { id: number; unread: boolean; date: string; actor: string; kind: string; context: string; verdict: string }[]
  unread: number
  page: number
  pages: number
}

export interface NotificationSettings {
  digest_enabled: boolean
  can_test: boolean
  mail_problem: string | null
  notice: string | null
  events: { key: string; label: string; enabled: boolean }[]
}

export function fetchNotifications(page: string, signal: AbortSignal) {
  return request<NotificationPage>(`/notifications?${new URLSearchParams({ page })}`, { signal })
}

export function fetchNotificationSettings(signal: AbortSignal) {
  return request<NotificationSettings>('/settings/notifications', { signal })
}
