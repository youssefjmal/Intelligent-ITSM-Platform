/**
 * Frontend login behavior contract tests.
 *
 * These tests validate the logic extracted from auth.tsx and login/page.tsx
 * to ensure the strict-login policy is respected on the frontend side.
 *
 * No Jest runner is required — run with: npx ts-node --esm tests/auth-login-behavior.test.ts
 * or include in a future Jest/Vitest setup.
 */

// ---------------------------------------------------------------------------
// Inline copies of the pure functions from auth.tsx so we can unit-test them
// without importing React or Next.js.
// ---------------------------------------------------------------------------

function mapAuthError(detail: string): string {
  if (detail.startsWith("account_locked_")) return "accountLocked"
  switch (detail) {
    case "ACCOUNT_LOCKED":     return "accountLocked"
    case "invalid_credentials": return "invalidCredentials"
    case "email_exists":        return "emailExists"
    case "email_not_verified":  return "emailNotVerified"
    case "password_too_short":  return "passwordTooShort"
    default:                    return "invalidCredentials"
  }
}

function parseLockedMinutes(detail: string): number | undefined {
  const m = detail.match(/account_locked_(\d+)min/)
  return m ? parseInt(m[1], 10) : undefined
}

// ---------------------------------------------------------------------------
// Minimal assertion helper
// ---------------------------------------------------------------------------

let passed = 0
let failed = 0

function expect(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected)
  if (ok) {
    console.log(`  ✓ ${label}`)
    passed++
  } else {
    console.error(`  ✗ ${label}`)
    console.error(`      expected: ${JSON.stringify(expected)}`)
    console.error(`      received: ${JSON.stringify(actual)}`)
    failed++
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

console.log("\n[auth] mapAuthError")

expect(
  "unknown email → invalidCredentials (not passwordTooShort)",
  mapAuthError("invalid_credentials"),
  "invalidCredentials",
)

expect(
  "password_too_short from server → passwordTooShort (only if server ever sends it)",
  mapAuthError("password_too_short"),
  "passwordTooShort",
)

expect(
  "account_locked_15min → accountLocked",
  mapAuthError("account_locked_15min"),
  "accountLocked",
)

expect(
  "account_locked_1min → accountLocked",
  mapAuthError("account_locked_1min"),
  "accountLocked",
)

expect(
  "ACCOUNT_LOCKED error_code → accountLocked",
  mapAuthError("ACCOUNT_LOCKED"),
  "accountLocked",
)

expect(
  "unrecognised detail falls back to invalidCredentials",
  mapAuthError("some_unexpected_error"),
  "invalidCredentials",
)

console.log("\n[auth] parseLockedMinutes")

expect(
  "extracts minutes from account_locked_15min",
  parseLockedMinutes("account_locked_15min"),
  15,
)

expect(
  "extracts minutes from account_locked_1min",
  parseLockedMinutes("account_locked_1min"),
  1,
)

expect(
  "returns undefined for invalid_credentials (not a lockout)",
  parseLockedMinutes("invalid_credentials"),
  undefined,
)

expect(
  "returns undefined for empty string",
  parseLockedMinutes(""),
  undefined,
)

console.log("\n[auth] continueWithEmail redirect contract")

// Simulate what login/page.tsx does with the result of continueWithEmail
function simulateLoginPageRouting(result: {
  error?: string
  requiresVerification?: boolean
  lockedMinutes?: number
}): "signup-success" | "error" | "locked" | "home" {
  if (result.error) {
    if (result.error === "accountLocked") return "locked"
    return "error"
  }
  if (result.requiresVerification) return "signup-success"
  return "home"
}

expect(
  "successful login → home",
  simulateLoginPageRouting({}),
  "home",
)

expect(
  "requiresVerification → signup-success (unverified existing user)",
  simulateLoginPageRouting({ requiresVerification: true }),
  "signup-success",
)

expect(
  "unknown email error → error (NOT signup-success)",
  simulateLoginPageRouting({ error: "invalidCredentials" }),
  "error",
)

expect(
  "locked account → locked (NOT signup-success, NOT generic error)",
  simulateLoginPageRouting({ error: "accountLocked", lockedMinutes: 15 }),
  "locked",
)

expect(
  "false requiresVerification with no error → home (not signup-success)",
  simulateLoginPageRouting({ requiresVerification: false }),
  "home",
)

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------

console.log(`\n${passed + failed} tests: ${passed} passed, ${failed} failed\n`)
if (failed > 0) process.exit(1)
