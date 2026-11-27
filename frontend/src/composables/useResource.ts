import { computed, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, errorMessage, request } from '../api/client'
import { useSession } from './useSession'

export function useResource<T>(path: () => string | null) {
  const route = useRoute()
  const router = useRouter()
  const session = useSession()
  const key = computed(path)
  const data = shallowRef<T>()
  const loading = ref(false)
  const saving = ref(false)
  const error = ref('')
  const revision = ref(0)
  const refresh = () => { revision.value++ }

  async function fail(err: unknown) {
    if (err instanceof ApiError && err.status === 401) {
      session.clear()
      await router.replace({ name: 'login', query: { next: route.fullPath } })
    } else {
      error.value = errorMessage(err)
    }
  }

  watch([key, revision], async ([url], [previous], onCleanup) => {
    if (url !== previous) data.value = undefined
    error.value = ''
    loading.value = Boolean(url)
    if (!url) return
    const controller = new AbortController()
    onCleanup(() => controller.abort())
    try {
      const result = await request<T>(url, { signal: controller.signal })
      if (!controller.signal.aborted) data.value = result
    } catch (err) {
      if (!controller.signal.aborted) await fail(err)
    } finally {
      if (!controller.signal.aborted) loading.value = false
    }
  }, { immediate: true })

  async function save<R = unknown>(url: string, fields: Record<string, string> | URLSearchParams = {}): Promise<R | undefined> {
    if (saving.value) return
    saving.value = true
    error.value = ''
    try {
      const source = key.value
      const result = await session.submit<R>(url, fields)
      if (key.value !== source) return
      return result
    } catch (err) {
      await fail(err)
    } finally {
      saving.value = false
    }
  }

  return { data, loading, saving, error, refresh, save }
}
