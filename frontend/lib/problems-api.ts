import { apiFetch } from "@/lib/api"

export type ProblemStatus = "open" | "investigating" | "known_error" | "resolved" | "closed"
export type ProblemCategory =
  | "infrastructure"
  | "network"
  | "security"
  | "application"
  | "service_request"
  | "hardware"
  | "email"
  | "problem"

type ApiProblem = {
  id: string
  title: string
  category: ProblemCategory
  status: ProblemStatus
  created_at: string
  updated_at: string
  last_seen_at?: string | null
  resolved_at?: string | null
  occurrences_count: number
  active_count: number
  root_cause?: string | null
  workaround?: string | null
  permanent_fix?: string | null
  similarity_key: string
  assignee?: string | null
}

export interface ProblemListItem {
  id: string
  title: string
  category: ProblemCategory
  status: ProblemStatus
  createdAt: string
  updatedAt: string
  lastSeenAt?: string
  resolvedAt?: string
  occurrencesCount: number
  activeCount: number
  rootCause?: string
  workaround?: string
  permanentFix?: string
  similarityKey: string
  assignee?: string
}

export interface ProblemDetail extends ProblemListItem {
  tickets: Array<{
    id: string
    title: string
    status: string
    assignee: string
    reporter: string
    created_at: string
    updated_at: string
  }>
  aiSuggestions: string[]
}

export interface ProblemAISuggestions {
  problemId: string
  category: ProblemCategory
  assignee?: string
  suggestions: Array<{ text: string; confidence: number }>
  rootCauseSuggestion?: string
  rootCauseConfidence?: number
  workaroundSuggestion?: string
  workaroundConfidence?: number
  permanentFixSuggestion?: string
  permanentFixConfidence?: number
}

export type ProblemAssignmentMode = "auto" | "manual"

export interface ProblemAssigneeOption {
  id: string
  name: string
  role: string
}

export interface ProblemAssigneeUpdateResult {
  problemId: string
  assignee: string
  updatedTickets: number
  mode: ProblemAssignmentMode
}

function mapProblem(problem: ApiProblem): ProblemListItem {
  return {
    id: problem.id,
    title: problem.title,
    category: problem.category,
    status: problem.status,
    createdAt: problem.created_at,
    updatedAt: problem.updated_at,
    lastSeenAt: problem.last_seen_at ?? undefined,
    resolvedAt: problem.resolved_at ?? undefined,
    occurrencesCount: problem.occurrences_count,
    activeCount: problem.active_count,
    rootCause: problem.root_cause ?? undefined,
    workaround: problem.workaround ?? undefined,
    permanentFix: problem.permanent_fix ?? undefined,
    similarityKey: problem.similarity_key,
    assignee: problem.assignee ?? undefined,
  }
}

export async function fetchProblems(filters: { status?: ProblemStatus; category?: ProblemCategory; activeOnly?: boolean } = {}): Promise<ProblemListItem[]> {
  const params = new URLSearchParams()
  if (filters.status) params.set("status", filters.status)
  if (filters.category) params.set("category", filters.category)
  if (filters.activeOnly) params.set("active_only", "true")
  const query = params.toString()
  const path = query ? `/problems?${query}` : "/problems"
  const rows = await apiFetch<ApiProblem[]>(path)
  return rows.map(mapProblem)
}

export async function fetchProblem(problemId: string): Promise<ProblemDetail> {
  const row = await apiFetch<
    ApiProblem & {
      tickets: Array<{
        id: string
        title: string
        status: string
        assignee: string
        reporter: string
        created_at: string
        updated_at: string
      }>
      ai_suggestions?: string[]
    }
  >(`/problems/${problemId}`)
  return {
    ...mapProblem(row),
    tickets: row.tickets,
    aiSuggestions: Array.isArray(row.ai_suggestions) ? row.ai_suggestions : [],
  }
}

export async function fetchProblemAISuggestions(problemId: string): Promise<ProblemAISuggestions> {
  const row = await apiFetch<{
    problem_id: string
    category: ProblemCategory
    assignee?: string | null
    suggestions: string[]
    suggestions_scored?: Array<{ text: string; confidence: number }>
    root_cause_suggestion?: string | null
    root_cause_confidence?: number | null
    workaround_suggestion?: string | null
    workaround_confidence?: number | null
    permanent_fix_suggestion?: string | null
    permanent_fix_confidence?: number | null
  }>(`/problems/${problemId}/ai-suggestions`)
  const scored =
    Array.isArray(row.suggestions_scored) && row.suggestions_scored.length > 0
      ? row.suggestions_scored
          .map((item) => ({
            text: String(item.text || "").trim(),
            confidence: Number.isFinite(item.confidence) ? Math.max(0, Math.min(100, Number(item.confidence))) : 0,
          }))
          .filter((item) => item.text.length > 0)
      : (Array.isArray(row.suggestions) ? row.suggestions : [])
          .map((text, index) => ({
            text: String(text || "").trim(),
            confidence: Math.max(55, 82 - index * 6),
          }))
          .filter((item) => item.text.length > 0)
  return {
    problemId: row.problem_id,
    category: row.category,
    assignee: row.assignee ?? undefined,
    suggestions: scored,
    rootCauseSuggestion: row.root_cause_suggestion ?? undefined,
    rootCauseConfidence: row.root_cause_confidence ?? undefined,
    workaroundSuggestion: row.workaround_suggestion ?? undefined,
    workaroundConfidence: row.workaround_confidence ?? undefined,
    permanentFixSuggestion: row.permanent_fix_suggestion ?? undefined,
    permanentFixConfidence: row.permanent_fix_confidence ?? undefined,
  }
}

export async function updateProblem(
  problemId: string,
  payload: {
    status?: ProblemStatus
    rootCause?: string
    workaround?: string
    permanentFix?: string
    resolutionComment?: string
  },
): Promise<ProblemListItem> {
  const row = await apiFetch<ApiProblem>(`/problems/${problemId}`, {
    method: "PATCH",
    body: JSON.stringify({
      ...(payload.status ? { status: payload.status } : {}),
      ...(payload.rootCause !== undefined ? { root_cause: payload.rootCause } : {}),
      ...(payload.workaround !== undefined ? { workaround: payload.workaround } : {}),
      ...(payload.permanentFix !== undefined ? { permanent_fix: payload.permanentFix } : {}),
      ...(payload.resolutionComment !== undefined ? { resolution_comment: payload.resolutionComment } : {}),
    }),
  })
  return mapProblem(row)
}

export async function resolveProblemLinkedTickets(problemId: string, resolutionComment: string): Promise<{ problemId: string; resolvedCount: number }> {
  const row = await apiFetch<{ problem_id: string; resolved_count: number }>(`/problems/${problemId}/resolve-linked-tickets`, {
    method: "POST",
    body: JSON.stringify({
      confirm: true,
      resolution_comment: resolutionComment,
    }),
  })
  return {
    problemId: row.problem_id,
    resolvedCount: row.resolved_count,
  }
}

export async function fetchProblemAssignees(): Promise<ProblemAssigneeOption[]> {
  const rows = await apiFetch<Array<{ id: string; name: string; role: string }>>("/users/assignees")
  return rows.map((row) => ({
    id: row.id,
    name: row.name,
    role: row.role,
  }))
}

export async function assignProblemAssignee(
  problemId: string,
  payload: { mode: ProblemAssignmentMode; assignee?: string },
): Promise<ProblemAssigneeUpdateResult> {
  const row = await apiFetch<{
    problem_id: string
    assignee: string
    updated_tickets: number
    mode: ProblemAssignmentMode
  }>(`/problems/${problemId}/assignee`, {
    method: "POST",
    body: JSON.stringify({
      mode: payload.mode,
      ...(payload.assignee ? { assignee: payload.assignee } : {}),
    }),
  })
  return {
    problemId: row.problem_id,
    assignee: row.assignee,
    updatedTickets: row.updated_tickets,
    mode: row.mode,
  }
}
