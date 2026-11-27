import { computed, onScopeDispose, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { errorMessage } from '../api/client'
import { useSession } from './useSession'

interface Person { id: number; name: string; away?: boolean }
interface SyncState { playing: boolean; t: number; rate: number }
type RoomMessage =
  | { type: 'welcome'; you: number; video_id: number; people: Person[]; leader: Person | null; state: SyncState }
  | { type: 'roster'; people: Person[]; leader: Person | null }
  | ({ type: 'state' } & SyncState)
  | { type: 'markers' }

const closedMessages: Record<number, string> = {
  4401: 'Sesja wygasła.',
  4403: 'Brak dostępu do nagrania.',
  4404: 'Pokój został zamknięty.',
  4409: 'Pokój jest już otwarty w innym oknie.',
  4410: 'Pokój jest pełny.',
}

export function useWatchRoom(video: () => HTMLVideoElement | undefined, videoId: () => number | undefined, refresh: () => void) {
  const route = useRoute()
  const router = useRouter()
  const { submit } = useSession()
  const me = ref<number>()
  const leader = ref<Person | null>(null)
  const people = ref<Person[]>([])
  const detached = ref(false)
  const online = ref(false)
  const creating = ref(false)
  const status = ref('')
  const playBlocked = ref(false)
  const room = computed(() => /^#room=([A-Za-z0-9_-]{8,80})$/.exec(route.hash)?.[1])
  const leading = computed(() => me.value !== undefined && leader.value?.id === me.value)
  const locked = computed(() => Boolean(room.value && !leading.value && !detached.value))
  const link = computed(() => {
    const id = videoId()
    if (!room.value || id === undefined) return ''
    const { href } = router.resolve({ name: 'recording', params: { id }, hash: `#room=${room.value}` })
    return new URL(href, location.origin).href
  })
  let socket: WebSocket | undefined
  let latest: (SyncState & { received: number }) | undefined
  let reconnect: ReturnType<typeof setTimeout> | undefined
  let outgoing: ReturnType<typeof setTimeout> | undefined
  let lastSeek = 0
  let attempts = 0

  function send(message: object) {
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message))
  }

  function sendState() {
    const element = video()
    if (!leading.value || !element || !Number.isFinite(element.currentTime)) return
    send({ type: 'state', t: element.currentTime, rate: element.playbackRate, playing: !element.paused && !element.ended })
  }

  function eventChanged() {
    if (!leading.value || outgoing) return
    outgoing = setTimeout(() => { outgoing = undefined; sendState() }, 100)
  }

  function sync(force = false) {
    const element = video()
    if (!locked.value || !latest || !element || element.readyState === 0) return
    element.playbackRate = latest.rate
    const now = performance.now()
    const position = latest.t + (latest.playing ? (now - latest.received) / 1000 * latest.rate : 0)
    const target = Math.min(position, Number.isFinite(element.duration) ? element.duration : position)
    if (Math.abs(element.currentTime - target) > (latest.playing ? 0.5 : 0.02)
        && !element.seeking && (force || now - lastSeek > 1000)) {
      element.currentTime = target
      lastSeek = now
    }
    if (!latest.playing) {
      element.pause()
      playBlocked.value = false
    } else if (element.paused && !element.ended && (!playBlocked.value || force)) {
      void element.play().then(() => { playBlocked.value = false }).catch(() => { playBlocked.value = true })
    }
  }

  function applyState(state: SyncState) {
    if (Number.isFinite(state.t) && Number.isFinite(state.rate) && state.rate > 0) {
      latest = { ...state, received: performance.now() }
      sync(true)
    }
  }

  function disconnect(explicit = false) {
    clearTimeout(reconnect)
    clearTimeout(outgoing)
    outgoing = undefined
    if (explicit) send({ type: 'leave' })
    const current = socket
    socket = undefined
    current?.close()
    online.value = false
    leader.value = null
    people.value = []
    me.value = undefined
    latest = undefined
    playBlocked.value = false
  }

  function connect(id: string) {
    if (room.value !== id || !videoId()) return
    const wsOrigin = location.origin.replace(/^http/, 'ws')
    const current = new WebSocket(`${wsOrigin}/ws/watch/${id}`)
    socket = current
    current.onmessage = event => {
      if (socket !== current || typeof event.data !== 'string') return
      let message: RoomMessage
      try { message = JSON.parse(event.data) as RoomMessage } catch { return }
      if (message.type === 'welcome') {
        if (message.video_id !== videoId()) {
          disconnect()
          void router.replace({ name: 'recording', params: { id: message.video_id }, hash: route.hash })
          return
        }
        online.value = true
        attempts = 0
        me.value = message.you
        leader.value = message.leader
        people.value = message.people
        status.value = 'Połączono'
        if (leading.value) sendState()
        else applyState(message.state)
      } else if (message.type === 'roster') {
        const wasLeading = leading.value
        leader.value = message.leader
        people.value = message.people
        if (leading.value && !wasLeading) sendState()
        else if (!leading.value && wasLeading) { latest = undefined; detached.value = false }
      } else if (message.type === 'state') {
        applyState(message)
      } else if (message.type === 'markers') {
        refresh()
      }
    }
    current.onclose = event => {
      if (socket !== current) return
      socket = undefined
      online.value = false
      const error = closedMessages[event.code]
      if (error || event.code >= 4000 || attempts >= 5) {
        status.value = error ?? 'Połączenie z pokojem zostało zakończone.'
        detached.value = true
        return
      }
      status.value = 'Połączenie przerwane. Ponawiam…'
      reconnect = setTimeout(() => connect(id), Math.min(15000, 1000 * 2 ** attempts++))
    }
  }

  watch([room, videoId], ([id, activeVideo]) => {
    disconnect()
    detached.value = false
    attempts = 0
    if (id && activeVideo) {
      status.value = 'Łączenie z pokojem…'
      connect(id)
    }
  }, { immediate: true })

  watch(video, (element, _, onCleanup) => {
    if (!element) return
    const events = ['play', 'pause', 'seeked', 'ratechange', 'loadedmetadata']
    events.forEach(event => element.addEventListener(event, eventChanged))
    onCleanup(() => events.forEach(event => element.removeEventListener(event, eventChanged)))
  })

  const heartbeat = setInterval(sendState, 2000)
  const alignment = setInterval(sync, 500)
  onScopeDispose(() => {
    disconnect()
    clearInterval(heartbeat)
    clearInterval(alignment)
  })

  async function create() {
    if (!videoId() || creating.value) return
    creating.value = true
    try {
      const { room } = await submit<{ room: string }>(`/api/videos/${videoId()}/watch`)
      await router.replace({ hash: `#room=${room}`, query: route.query })
    } catch (err) {
      status.value = errorMessage(err)
    } finally {
      creating.value = false
    }
  }

  async function leave() {
    disconnect(true)
    await router.replace({ hash: '', query: route.query })
  }

  function toggleDetached() {
    detached.value = !detached.value
    sync(true)
  }

  return { room, link, me, people, leader, leading, online, locked, detached, status, playBlocked, creating, create, leave,
    toggleDetached, handover: (id: number) => send({ type: 'handover', to: id }), resume: () => sync(true) }
}
