
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api"

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
  }
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    credentials: "include",
  })

  if (!res.ok) {
    let detail = "request_failed"
    try {
      const data = await res.json()
      detail = data.detail || detail
    } catch {
      // ignore
    }
    throw new ApiError(res.status, detail)
  }

  if (res.status === 204) return null as T
  return res.json() as Promise<T>
}
