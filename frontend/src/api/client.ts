export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Wystąpił nieoczekiwany błąd.'
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  return request<T>(`/api/frontend${path}`, options)
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('Accept', 'application/json')
  let response: Response
  try {
    response = await fetch(path, {
      credentials: 'same-origin', ...options, headers,
    })
  } catch (error) {
    if (options.signal?.aborted) throw error
    throw new ApiError('Nie można połączyć się z serwerem. Sprawdź połączenie i spróbuj ponownie.', 0)
  }
  const data: unknown = response.status === 204 ? null : await response.json().catch(() => null)
  if (!response.ok) {
    const detail = data && typeof data === 'object' && 'detail' in data ? data.detail : null
    throw new ApiError(
      typeof detail === 'string' ? detail : 'Nie udało się wykonać operacji. Spróbuj ponownie.',
      response.status,
    )
  }
  if (data === null && response.status !== 204) {
    throw new ApiError('Serwer zwrócił nieoczekiwaną odpowiedź.', response.status)
  }
  return data as T
}
