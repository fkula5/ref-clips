import { readonly, ref } from 'vue'
import { fetchCsrf, fetchSession, loginRequest, logoutRequest } from '../api/auth'
import { ApiError, request } from '../api/client'
import type { LoginCredentials, User } from '../types/api'

// A single session is shared by route guards, views and the layout.
const user = ref<User | null>(null)
let csrf = ''
let initialized = false
let pending: Promise<void> | null = null

async function initialize(): Promise<void> {
  if (initialized) return
  if (pending) return pending
  pending = (async () => {
    try {
      const session = await fetchSession()
      user.value = session.user
      csrf = session.csrf_token
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error
      user.value = null
      csrf = (await fetchCsrf()).csrf_token
    }
    initialized = true
  })()
  try { await pending } finally { pending = null }
}

async function login(credentials: LoginCredentials): Promise<void> {
  await initialize()
  // Refresh the anonymous token: another tab may have replaced its cookie.
  csrf = (await fetchCsrf()).csrf_token
  const session = await loginRequest(credentials, csrf)
  user.value = session.user
  csrf = session.csrf_token
  initialized = true
}

function clear(): void {
  user.value = null
  csrf = ''
  initialized = false
}

async function logout(): Promise<void> {
  try {
    await logoutRequest(csrf)
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error
  }
  clear()
}

export function useSession() {
  async function csrfHeaders() {
    await initialize()
    return { 'X-CSRF-Token': csrf }
  }

  async function submit<T = null>(path: string, fields: Record<string, string> | URLSearchParams = {}) {
    return request<T>(path, {
      method: 'POST', headers: await csrfHeaders(), body: new URLSearchParams(fields),
    })
  }
  return { user: readonly(user), initialize, login, logout, clear, submit, csrfHeaders }
}
