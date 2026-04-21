/**
 * Chat response payload normalization contract tests.
 *
 * Run with a TS runner if desired. This mirrors the lightweight frontend test
 * style already used in this repo for pure logic checks.
 */

export {}

type ProblemListPayload = {
  type: "problem_list"
  problems: Array<{ id: string; title: string }>
  total_count: number
}

type ChatResponsePayload = ProblemListPayload

function normalizeResponsePayload(payload: unknown): ChatResponsePayload | null {
  if (!payload) return null

  if (typeof payload === "string") {
    const text = payload.trim()
    if (!text) return null
    try {
      return normalizeResponsePayload(JSON.parse(text))
    } catch {
      return null
    }
  }

  if (typeof payload !== "object") return null

  const candidate = payload as Record<string, unknown>
  if (typeof candidate.type === "string") {
    return candidate as ChatResponsePayload
  }
  if (typeof candidate.response_type === "string") {
    return {
      ...candidate,
      type: candidate.response_type,
    } as ChatResponsePayload
  }
  if ("response_payload" in candidate) {
    return normalizeResponsePayload(candidate.response_payload)
  }
  if ("responsePayload" in candidate) {
    return normalizeResponsePayload(candidate.responsePayload)
  }
  if ("payload" in candidate) {
    return normalizeResponsePayload(candidate.payload)
  }
  return null
}

let chatPayloadPassed = 0
let chatPayloadFailed = 0

function expectChatPayload(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected)
  if (ok) {
    console.log(`  ok ${label}`)
    chatPayloadPassed += 1
  } else {
    console.error(`  fail ${label}`)
    console.error(`    expected: ${JSON.stringify(expected)}`)
    console.error(`    received: ${JSON.stringify(actual)}`)
    chatPayloadFailed += 1
  }
}

const basePayload = {
  type: "problem_list",
  problems: [{ id: "PB-1", title: "VPN MFA loop" }],
  total_count: 1,
} satisfies ProblemListPayload

console.log("\n[chat] normalizeResponsePayload")

expectChatPayload("accepts direct structured payload", normalizeResponsePayload(basePayload), basePayload)
expectChatPayload(
  "accepts nested response_payload wrapper",
  normalizeResponsePayload({ response_payload: basePayload }),
  basePayload,
)
expectChatPayload(
  "accepts nested camelCase responsePayload wrapper",
  normalizeResponsePayload({ responsePayload: basePayload }),
  basePayload,
)
expectChatPayload(
  "accepts stringified structured payload",
  normalizeResponsePayload(JSON.stringify(basePayload)),
  basePayload,
)

console.log(`\n${chatPayloadPassed + chatPayloadFailed} tests: ${chatPayloadPassed} passed, ${chatPayloadFailed} failed\n`)
if (chatPayloadFailed > 0) process.exit(1)
