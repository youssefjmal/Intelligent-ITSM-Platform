/**
 * Frontend login behavior contract tests.
 *
 * These tests validate the logic extracted from auth.tsx and login/page.tsx
 * to ensure the strict-login policy is respected on the frontend side.
 *
 * No Jest runner is required - run with: npx ts-node --esm tests/auth-login-behavior.test.ts
 * or include in a future Jest/Vitest setup.
 */

export {}

function mapAuthError(detail: string): string {
  if (detail.startsWith("account_locked_")) return "accountLocked"
  switch (detail) {
    case "ACCOUNT_LOCKED": return "accountLocked"
    case "invalid_credentials": return "invalidCredentials"
    case "email_exists": return "emailExists"
    case "email_not_verified": return "emailNotVerified"
    case "password_too_short": return "passwordTooShort"
    default: return "invalidCredentials"
  }
}

function parseLockedMinutes(detail: string): number | undefined {
  const match = detail.match(/account_locked_(\d+)min/)
  return match ? parseInt(match[1], 10) : undefined
}

let authPassed = 0
let authFailed = 0

function expectAuth(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected)
  if (ok) {
    console.log(`  ok ${label}`)
    authPassed += 1
  } else {
    console.error(`  fail ${label}`)
    console.error(`      expected: ${JSON.stringify(expected)}`)
    console.error(`      received: ${JSON.stringify(actual)}`)
    authFailed += 1
  }
}

console.log("\n[auth] mapAuthError")

expectAuth(
  "unknown email -> invalidCredentials (not passwordTooShort)",
  mapAuthError("invalid_credentials"),
  "invalidCredentials",
)

expectAuth(
  "password_too_short from server -> passwordTooShort",
  mapAuthError("password_too_short"),
  "passwordTooShort",
)

expectAuth(
  "account_locked_15min -> accountLocked",
  mapAuthError("account_locked_15min"),
  "accountLocked",
)

expectAuth(
  "account_locked_1min -> accountLocked",
  mapAuthError("account_locked_1min"),
  "accountLocked",
)

expectAuth(
  "ACCOUNT_LOCKED error_code -> accountLocked",
  mapAuthError("ACCOUNT_LOCKED"),
  "accountLocked",
)

expectAuth(
  "unrecognised detail falls back to invalidCredentials",
  mapAuthError("some_unexpected_error"),
  "invalidCredentials",
)

console.log("\n[auth] parseLockedMinutes")

expectAuth(
  "extracts minutes from account_locked_15min",
  parseLockedMinutes("account_locked_15min"),
  15,
)

expectAuth(
  "extracts minutes from account_locked_1min",
  parseLockedMinutes("account_locked_1min"),
  1,
)

expectAuth(
  "returns undefined for invalid_credentials",
  parseLockedMinutes("invalid_credentials"),
  undefined,
)

expectAuth(
  "returns undefined for empty string",
  parseLockedMinutes(""),
  undefined,
)

console.log("\n[auth] continueWithEmail redirect contract")

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

expectAuth(
  "successful login -> home",
  simulateLoginPageRouting({}),
  "home",
)

expectAuth(
  "requiresVerification -> signup-success",
  simulateLoginPageRouting({ requiresVerification: true }),
  "signup-success",
)

expectAuth(
  "unknown email error -> error",
  simulateLoginPageRouting({ error: "invalidCredentials" }),
  "error",
)

expectAuth(
  "locked account -> locked",
  simulateLoginPageRouting({ error: "accountLocked", lockedMinutes: 15 }),
  "locked",
)

expectAuth(
  "false requiresVerification with no error -> home",
  simulateLoginPageRouting({ requiresVerification: false }),
  "home",
)

console.log(`\n${authPassed + authFailed} tests: ${authPassed} passed, ${authFailed} failed\n`)
if (authFailed > 0) process.exit(1)
