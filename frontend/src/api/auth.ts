import { api } from './client'
import type { CsrfResponse, LoginCredentials, SessionResponse } from '../types/api'

export const fetchSession = () => api<SessionResponse>('/session')
export const fetchCsrf = () => api<CsrfResponse>('/csrf')

export function loginRequest(credentials: LoginCredentials, csrf: string) {
  return api<SessionResponse>('/login', {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrf },
    body: new URLSearchParams({ ...credentials }),
  })
}

export function logoutRequest(csrf: string) {
  return api<null>('/logout', { method: 'POST', headers: { 'X-CSRF-Token': csrf } })
}
