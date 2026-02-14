export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api"
let refreshInFlight: Promise<boolean> | null = null

export function buildApiUrl(path: string): string {
  return `${API_BASE}${path}`
}

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
  }
}

function shouldTryRefresh(path: string): boolean {
  return ![
    "/auth/login",
    "/auth/email-login",
    "/auth/logout",
    "/auth/register",
    "/auth/verify",
    "/auth/verify-code",
    "/auth/forgot-password",
    "/auth/reset-password",
    "/auth/refresh",
    "/auth/token",
    "/auth/token/refresh",
  ].includes(path)
}

async function refreshSession(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = fetch(buildApiUrl("/auth/refresh"), {
      method: "POST",
      credentials: "include",
    })
      .then((res) => res.ok)
      .catch(() => false)
      .finally(() => {
        refreshInFlight = null
      })
  }
  return refreshInFlight
}

async function apiFetchInternal<T>(path: string, options: RequestInit, canRetry: boolean): Promise<T> {
  let res: Response
  try {
    res = await fetch(buildApiUrl(path), {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
      credentials: "include",
    })
  } catch {
    throw new ApiError(0, "network_error")
  }

  if (res.status === 401 && canRetry && shouldTryRefresh(path)) {
    const refreshed = await refreshSession()
    if (refreshed) {
      return apiFetchInternal<T>(path, options, false)
    }
  }

  if (!res.ok) {
    let detail = "request_failed"
    try {
      const data = await res.json()
      detail = data.detail || data.message || data.error_code || detail
    } catch {
      // ignore
    }
    throw new ApiError(res.status, detail)
  }

  if (res.status === 204) return null as T
  return res.json() as Promise<T>
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  return apiFetchInternal<T>(path, options, true)
}
