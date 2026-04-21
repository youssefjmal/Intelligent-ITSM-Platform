export const NOTIFICATIONS_STREAM_PATH = "/notifications/stream"
export const NOTIFICATIONS_POLL_INTERVAL_MS = 15_000

export interface EventSourceLike {
  close(): void
  onmessage: ((event: MessageEvent<string>) => void) | null
  onerror: ((event: Event) => void) | null
}

interface StartUnreadCountSubscriptionOptions {
  apiBase: string
  eventSourceSupported: boolean
  createEventSource: (url: string) => EventSourceLike
  loadUnreadCount: () => Promise<void> | void
  onCount: (count: number) => void
  setIntervalFn: (callback: () => void, ms: number) => number
  clearIntervalFn: (id: number) => void
}

export function startUnreadCountSubscription(options: StartUnreadCountSubscriptionOptions): () => void {
  const {
    apiBase,
    eventSourceSupported,
    createEventSource,
    loadUnreadCount,
    onCount,
    setIntervalFn,
    clearIntervalFn,
  } = options

  let pollTimer: number | null = null
  let eventSource: EventSourceLike | null = null

  const ensurePolling = () => {
    if (pollTimer !== null) return
    pollTimer = setIntervalFn(() => {
      void loadUnreadCount()
    }, NOTIFICATIONS_POLL_INTERVAL_MS)
  }

  if (eventSourceSupported) {
    eventSource = createEventSource(`${apiBase}${NOTIFICATIONS_STREAM_PATH}`)
    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as { unread_count: number }
        onCount(data.unread_count)
      } catch {
        // ignore malformed frames
      }
    }
    eventSource.onerror = () => {
      if (eventSource) {
        eventSource.close()
        eventSource = null
      }
      ensurePolling()
    }
  } else {
    ensurePolling()
  }

  return () => {
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
    if (pollTimer !== null) {
      clearIntervalFn(pollTimer)
      pollTimer = null
    }
  }
}
