import {
  NOTIFICATIONS_POLL_INTERVAL_MS,
  startUnreadCountSubscription,
  type EventSourceLike,
} from "../lib/notifications-stream"

export {}

let notificationsStreamPassed = 0
let notificationsStreamFailed = 0

function expectNotificationStream(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected)
  if (ok) {
    console.log(`  ok ${label}`)
    notificationsStreamPassed += 1
  } else {
    console.error(`  fail ${label}`)
    console.error(`    expected: ${JSON.stringify(expected)}`)
    console.error(`    received: ${JSON.stringify(actual)}`)
    notificationsStreamFailed += 1
  }
}

class FakeEventSource implements EventSourceLike {
  public closed = false
  public onmessage: ((event: MessageEvent<string>) => void) | null = null
  public onerror: ((event: Event) => void) | null = null
  public readonly url: string

  constructor(url: string) {
    this.url = url
  }

  close(): void {
    this.closed = true
  }
}

console.log("\n[notifications-stream] SSE success path")
{
  let latestCount = 0
  let intervalCalls = 0
  const created: FakeEventSource[] = []

  const cleanup = startUnreadCountSubscription({
    apiBase: "http://localhost:8000/api",
    eventSourceSupported: true,
    createEventSource: (url) => {
      const source = new FakeEventSource(url)
      created.push(source)
      return source
    },
    loadUnreadCount: async () => {
      intervalCalls += 1
    },
    onCount: (count) => {
      latestCount = count
    },
    setIntervalFn: () => {
      intervalCalls += 1
      return 1
    },
    clearIntervalFn: () => undefined,
  })

  const source = created[0]
  if (!source) throw new Error("expected EventSource instance")
  source.onmessage?.({ data: JSON.stringify({ unread_count: 9 }) } as MessageEvent<string>)

  expectNotificationStream("SSE message updates count", latestCount, 9)
  expectNotificationStream("SSE does not start polling while healthy", intervalCalls, 0)

  cleanup()
  expectNotificationStream("cleanup closes event source", source.closed, true)
}

console.log("\n[notifications-stream] SSE fallback path")
{
  const timers: Array<() => void> = []
  const cleared: number[] = []
  let loadCalls = 0
  const created: FakeEventSource[] = []

  const cleanup = startUnreadCountSubscription({
    apiBase: "http://localhost:8000/api",
    eventSourceSupported: true,
    createEventSource: (url) => {
      const source = new FakeEventSource(url)
      created.push(source)
      return source
    },
    loadUnreadCount: async () => {
      loadCalls += 1
    },
    onCount: () => undefined,
    setIntervalFn: (callback, ms) => {
      expectNotificationStream("fallback poll interval is 15s", ms, NOTIFICATIONS_POLL_INTERVAL_MS)
      timers.push(callback)
      return timers.length
    },
    clearIntervalFn: (id) => {
      cleared.push(id)
    },
  })

  const source = created[0]
  if (!source) throw new Error("expected EventSource instance")
  source.onerror?.({} as Event)
  timers[0]?.()

  expectNotificationStream("SSE error closes stream", source.closed, true)
  expectNotificationStream("polling runs after SSE error", loadCalls, 1)

  cleanup()
  expectNotificationStream("cleanup clears fallback timer", cleared, [1])
}

console.log("\n[notifications-stream] polling-only path")
{
  const cleared: number[] = []

  const cleanup = startUnreadCountSubscription({
    apiBase: "http://localhost:8000/api",
    eventSourceSupported: false,
    createEventSource: () => {
      throw new Error("should not create event source")
    },
    loadUnreadCount: async () => undefined,
    onCount: () => undefined,
    setIntervalFn: () => 42,
    clearIntervalFn: (id) => {
      cleared.push(id)
    },
  })

  cleanup()
  expectNotificationStream("cleanup clears polling timer when SSE unavailable", cleared, [42])
}

console.log(`\n${notificationsStreamPassed + notificationsStreamFailed} tests: ${notificationsStreamPassed} passed, ${notificationsStreamFailed} failed\n`)
if (notificationsStreamFailed > 0) process.exit(1)
