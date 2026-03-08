// Simple chat UI that calls the backend AI endpoint.
"use client"

import { useEffect, useRef, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Badge } from "@/components/ui/badge"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import { ApiError, apiFetch } from "@/lib/api"
import { Send, Bot, User, Sparkles, RotateCcw, Ticket, CheckCircle2, Lightbulb, AlertCircle, BookOpen, ThumbsUp, ThumbsDown } from "lucide-react"
import { useI18n } from "@/lib/i18n"
import { useAuth } from "@/lib/auth"
import { useRouter } from "next/navigation"

type ChatMessage = {
  id: string
  role: "user" | "assistant"
  content: string
  createdAt: string
  ticketDraft?: TicketDraft
  ticketAction?: string | null
  ragGrounding?: boolean
  suggestions?: SuggestionBundle
  draftContext?: DraftContext | null
  actions?: string[]
}

type TicketDraft = {
  title: string
  description: string
  priority: "critical" | "high" | "medium" | "low"
  category: "infrastructure" | "network" | "security" | "application" | "service_request" | "hardware" | "email" | "problem"
  tags: string[]
  assignee?: string | null
}

type TicketDigestRow = {
  id: string
  title: string
  priority: string
  status: string
  assignee: string
}

type SuggestionTicket = {
  id: string
  title: string
  similarity_score: number
  status: string
  resolution_snippet?: string | null
}

type SuggestionProblem = {
  id: string
  title: string
  match_reason: string
  root_cause?: string | null
  affected_tickets?: number | null
}

type SuggestionKb = {
  id: string
  title: string
  excerpt: string
  similarity_score: number
  source_type?: string | null
}

type SolutionRecommendation = {
  text: string
  source: string
  source_id?: string | null
  evidence_snippet?: string | null
  quality_score: number
  confidence: number
  helpful_votes?: number
  not_helpful_votes?: number
  reason?: string | null
}

type SuggestionBundle = {
  tickets: SuggestionTicket[]
  problems: SuggestionProblem[]
  kb_articles: SuggestionKb[]
  solution_recommendations?: SolutionRecommendation[]
  confidence: number
  source: "embedding" | "hybrid" | "llm_fallback" | string
}

type DraftContext = {
  pre_filled_description: string
  suggested_priority?: string | null
  related_tickets: string[]
  confidence: number
}

const MAX_CHAT_MESSAGES = 40
const MAX_CHAT_CONTENT_LEN = 4000

function normalizeAssistantReply(content: string, locale: string): string {
  const raw = (content || "").trim()
  if (!raw.startsWith("{") || !raw.endsWith("}")) return raw
  try {
    const data = JSON.parse(raw) as {
      reply?: unknown
      solution?: unknown
      ticket?: { title?: unknown } | null
    }
    const reply = typeof data.reply === "string" ? data.reply.trim() : ""
    if (reply) return reply

    if (typeof data.solution === "string" && data.solution.trim()) return data.solution.trim()
    if (Array.isArray(data.solution)) {
      const text = data.solution
        .map((item) => String(item || "").trim())
        .filter(Boolean)
        .join(" ")
      if (text) return text
    }

    const title = String(data.ticket?.title || "").trim()
    if (title) {
      return locale === "fr"
        ? `Resultat IA: ${title}`
        : `AI result: ${title}`
    }
    return raw
  } catch {
    return raw
  }
}

function parseTicketDigest(content: string): { header: string; rows: TicketDigestRow[]; extra: string | null } | null {
  const lines = content
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
  if (!lines.length) return null

  const rows: TicketDigestRow[] = []
  let extra: string | null = null
  for (const line of lines.slice(1)) {
    if (line.startsWith("...")) {
      extra = line
      continue
    }
    if (!line.startsWith("-")) continue
    const clean = line.replace(/^-+\s*/, "")
    const parts = clean.split("|").map((part) => part.trim())
    if (parts.length < 5) continue
    const [id, title, priority, status, ...assigneeParts] = parts
    rows.push({
      id,
      title,
      priority,
      status,
      assignee: assigneeParts.join(" | "),
    })
  }

  if (!rows.length) return null
  return {
    header: lines[0],
    rows,
    extra,
  }
}

function priorityBadgeClass(priority: string): string {
  const p = priority.toLowerCase()
  if (p.includes("critical") || p.includes("critique")) return "border-red-200 bg-red-500/10 text-red-700"
  if (p.includes("high") || p.includes("haute")) return "border-orange-200 bg-orange-500/10 text-orange-700"
  if (p.includes("medium") || p.includes("moyenne")) return "border-amber-200 bg-amber-500/10 text-amber-700"
  return "border-slate-200 bg-slate-500/10 text-slate-700"
}

function statusBadgeClass(status: string): string {
  const s = status.toLowerCase()
  if (s.includes("open") || s.includes("ouvert")) return "border-blue-200 bg-blue-500/10 text-blue-700"
  if (s.includes("progress") || s.includes("cours")) return "border-cyan-200 bg-cyan-500/10 text-cyan-700"
  if (s.includes("pending") || s.includes("attente")) return "border-yellow-200 bg-yellow-500/10 text-yellow-700"
  if (s.includes("resolved") || s.includes("resolu")) return "border-emerald-200 bg-emerald-500/10 text-emerald-700"
  if (s.includes("closed") || s.includes("clos")) return "border-slate-200 bg-slate-500/10 text-slate-700"
  return "border-muted bg-muted/60 text-foreground"
}

function formatMessageTime(value: string, locale: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  return date.toLocaleTimeString(locale === "fr" ? "fr-FR" : "en-US", {
    hour: "2-digit",
    minute: "2-digit",
  })
}

function isCriticalDigestHeader(header: string): boolean {
  const value = (header || "").toLowerCase()
  return value.includes("critical") || value.includes("critiq")
}

function extractMoreCount(extra: string | null): number {
  if (!extra) return 0
  const match = extra.match(/\d+/)
  if (!match) return 0
  const parsed = Number(match[0])
  return Number.isFinite(parsed) ? parsed : 0
}

function hasSuggestions(bundle?: SuggestionBundle): boolean {
  if (!bundle) return false
  return (
    bundle.tickets.length > 0 ||
    bundle.problems.length > 0 ||
    bundle.kb_articles.length > 0 ||
    (bundle.solution_recommendations || []).length > 0
  )
}

type AssistantTextBlock =
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }

function parseAssistantTextBlocks(content: string): AssistantTextBlock[] {
  const lines = String(content || "").replace(/\r/g, "").split("\n")
  const blocks: AssistantTextBlock[] = []
  let i = 0

  const bulletPattern = /^[-*\u2022]\s+(.+)$/
  const orderedPattern = /^\d+[\.\)]\s+(.+)$/

  while (i < lines.length) {
    const line = lines[i].trim()
    if (!line) {
      i += 1
      continue
    }

    const bulletMatch = line.match(bulletPattern)
    const orderedMatch = line.match(orderedPattern)
    if (bulletMatch || orderedMatch) {
      const ordered = Boolean(orderedMatch)
      const items: string[] = []
      while (i < lines.length) {
        const current = lines[i].trim()
        const match = ordered ? current.match(orderedPattern) : current.match(bulletPattern)
        if (!match) break
        const value = String(match[1] || "").trim()
        if (value) items.push(value)
        i += 1
      }
      if (items.length) {
        blocks.push({ kind: "list", ordered, items })
      }
      continue
    }

    const paragraphLines: string[] = [line]
    i += 1
    while (i < lines.length) {
      const current = lines[i].trim()
      if (!current) break
      if (bulletPattern.test(current) || orderedPattern.test(current)) break
      paragraphLines.push(current)
      i += 1
    }
    blocks.push({ kind: "paragraph", text: paragraphLines.join(" ") })
  }

  return blocks
}

export function TicketChatbot() {
  const { t, locale } = useI18n()
  const { user, hasPermission } = useAuth()
  const router = useRouter()
  const [input, setInput] = useState("")
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [creatingId, setCreatingId] = useState<string | null>(null)
  const [criticalOverflowRows, setCriticalOverflowRows] = useState<TicketDigestRow[]>([])
  const [criticalOverflowLoaded, setCriticalOverflowLoaded] = useState(false)
  const [criticalOverflowLoading, setCriticalOverflowLoading] = useState(false)
  const [feedbackSubmitting, setFeedbackSubmitting] = useState<Record<string, boolean>>({})
  const scrollRef = useRef<HTMLDivElement>(null)

  const quickPrompts = [
    t("chat.prompt1"),
    t("chat.prompt2"),
    t("chat.prompt3"),
    t("chat.prompt4"),
  ]

  async function loadCriticalOverflowRows() {
    if (criticalOverflowLoaded || criticalOverflowLoading) return
    setCriticalOverflowLoading(true)
    try {
      const rows = await apiFetch<
        Array<{
          id: string
          title: string
          priority: "critical" | "high" | "medium" | "low"
          status:
            | "open"
            | "in-progress"
            | "waiting-for-customer"
            | "waiting-for-support-vendor"
            | "pending"
            | "resolved"
            | "closed"
          assignee: string
          created_at?: string
          updated_at: string
        }>
      >("/tickets")
      const active = new Set([
        "open",
        "in-progress",
        "waiting-for-customer",
        "waiting-for-support-vendor",
        "pending",
      ])
      const mapped = rows
        .filter((ticket) => ticket.priority === "critical" && active.has(ticket.status))
        .sort((left, right) => {
          const leftTs = new Date(left.created_at || left.updated_at).getTime()
          const rightTs = new Date(right.created_at || right.updated_at).getTime()
          return rightTs - leftTs
        })
        .slice(3, 12)
        .map((ticket) => ({
          id: ticket.id,
          title: ticket.title,
          priority: t("priority.critical"),
          status:
            ticket.status === "open"
              ? t("status.open")
              : ticket.status === "in-progress"
                ? t("status.inProgress")
                : ticket.status === "waiting-for-customer"
                  ? t("status.waitingForCustomer")
                  : ticket.status === "waiting-for-support-vendor"
                    ? t("status.waitingForSupportVendor")
                : ticket.status === "pending"
                  ? t("status.pending")
                  : ticket.status === "resolved"
                    ? t("status.resolved")
                    : t("status.closed"),
          assignee: ticket.assignee,
        }))
      setCriticalOverflowRows(mapped)
    } catch {
      setCriticalOverflowRows([])
    } finally {
      setCriticalOverflowLoaded(true)
      setCriticalOverflowLoading(false)
    }
  }

  function handleApplySuggestion(messageId: string, solution: string, sourceId: string) {
    const normalized = solution.trim()
    if (!normalized) return
    setMessages((prev) =>
      prev.map((item) => {
        if (item.id !== messageId) return item
        if (item.ticketDraft) {
          const marker = `Suggested fix (from ${sourceId}):`
          if (item.ticketDraft.description.includes(marker)) return item
          return {
            ...item,
            ticketDraft: {
              ...item.ticketDraft,
              description: `${item.ticketDraft.description}\n\n${marker}\n${normalized}`.trim(),
            },
          }
        }
        return item
      }),
    )
    setInput((current) => {
      if (current.trim()) return current
      return `Create a ticket for this issue. Suggested fix: ${normalized}`
    })
  }

  function getChatErrorMessage(error: unknown): string {
    if (error instanceof ApiError) {
      if (error.status === 401) {
        return locale === "fr" ? "Session expiree. Reconnectez-vous." : "Session expired. Please sign in again."
      }
      if (error.status === 422) {
        return locale === "fr"
          ? "Message invalide ou conversation trop longue. Reinitialisez le chat."
          : "Invalid message or conversation too long. Reset the chat."
      }
    }
    return t("chat.errorReply")
  }

  async function submitSolutionFeedback(
    messageId: string,
    recommendation: SolutionRecommendation,
    vote: "helpful" | "not_helpful",
    query: string,
  ) {
    const key = `${messageId}-${recommendation.source}-${recommendation.source_id || recommendation.text.slice(0, 24)}-${vote}`
    if (feedbackSubmitting[key]) return
    setFeedbackSubmitting((prev) => ({ ...prev, [key]: true }))
    try {
      await apiFetch("/ai/feedback", {
        method: "POST",
        body: JSON.stringify({
          query,
          recommendation_text: recommendation.text,
          source: recommendation.source,
          source_id: recommendation.source_id || null,
          vote,
          context: {
            ui: "ticket_chatbot",
            quality_score: recommendation.quality_score,
            confidence: recommendation.confidence,
          },
        }),
      })
      setMessages((prev) =>
        prev.map((msg) => {
          if (msg.id !== messageId || !msg.suggestions?.solution_recommendations) return msg
          const nextRows = msg.suggestions.solution_recommendations.map((row) => {
            if (row.text !== recommendation.text || row.source !== recommendation.source || (row.source_id || "") !== (recommendation.source_id || "")) {
              return row
            }
            return {
              ...row,
              helpful_votes: (row.helpful_votes || 0) + (vote === "helpful" ? 1 : 0),
              not_helpful_votes: (row.not_helpful_votes || 0) + (vote === "not_helpful" ? 1 : 0),
            }
          })
          return { ...msg, suggestions: { ...msg.suggestions, solution_recommendations: nextRows } }
        }),
      )
    } catch {
      // no-op
    } finally {
      setFeedbackSubmitting((prev) => ({ ...prev, [key]: false }))
    }
  }

  function renderAssistantMessage(message: ChatMessage) {
    if (message.ticketAction === "show_ticket") {
      const parsed = parseTicketDigest(message.content)
      if (parsed) {
        const isCriticalDigest = isCriticalDigestHeader(parsed.header)
        const visibleRows = parsed.rows.slice(0, 3)
        const overflowRows = parsed.rows.slice(3)
        const hoverRows = overflowRows.length > 0 ? overflowRows : criticalOverflowRows
        const moreCount = extractMoreCount(parsed.extra)

        return (
          <div className="space-y-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{parsed.header}</p>
            <div className="space-y-2">
              {visibleRows.map((row) => (
                <div key={`${row.id}-${row.title}`} className="rounded-lg border border-border bg-background/60 p-2.5">
                  <div className="text-xs font-semibold text-foreground">
                    {row.id}
                    <span className="mx-1 text-muted-foreground">-</span>
                    <span className="font-medium">{row.title}</span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <Badge variant="outline" className={`text-[10px] ${priorityBadgeClass(row.priority)}`}>
                      {row.priority}
                    </Badge>
                    <Badge variant="outline" className={`text-[10px] ${statusBadgeClass(row.status)}`}>
                      {row.status}
                    </Badge>
                    <Badge variant="outline" className="text-[10px] border-border bg-muted/60">
                      {row.assignee}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
            {parsed.extra && isCriticalDigest ? (
              <div className="pt-0.5" onClick={(event) => event.stopPropagation()}>
                <HoverCard
                  openDelay={90}
                  closeDelay={80}
                  onOpenChange={(open) => {
                    if (open && !overflowRows.length) {
                      loadCriticalOverflowRows().catch(() => {})
                    }
                  }}
                >
                  <HoverCardTrigger asChild>
                    <button type="button" className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground">
                      {parsed.extra}
                    </button>
                  </HoverCardTrigger>
                  <HoverCardContent className="w-96 space-y-2 p-3">
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      {locale === "fr" ? "Autres tickets critiques" : "Other critical tickets"}
                    </p>
                    {criticalOverflowLoading ? (
                      <p className="text-xs text-muted-foreground">{locale === "fr" ? "Chargement..." : "Loading..."}</p>
                    ) : hoverRows.length === 0 ? (
                      <p className="text-xs text-muted-foreground">
                        {locale === "fr" ? "Aucun ticket critique supplementaire." : "No additional critical tickets."}
                      </p>
                    ) : (
                      <div className="space-y-2">
                        {hoverRows.slice(0, moreCount > 0 ? moreCount : 8).map((row) => (
                          <div key={`overflow-${row.id}-${row.title}`} className="rounded-lg border border-border/70 bg-background/60 p-2">
                            <p className="line-clamp-1 text-xs font-semibold text-foreground">
                              {row.id} - {row.title}
                            </p>
                            <div className="mt-1.5 flex flex-wrap gap-1.5">
                              <Badge variant="outline" className={`text-[10px] ${priorityBadgeClass(row.priority)}`}>
                                {row.priority}
                              </Badge>
                              <Badge variant="outline" className={`text-[10px] ${statusBadgeClass(row.status)}`}>
                                {row.status}
                              </Badge>
                              <Badge variant="outline" className="border-border bg-muted/60 text-[10px]">
                                {row.assignee}
                              </Badge>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </HoverCardContent>
                </HoverCard>
              </div>
            ) : parsed.extra ? (
              <p className="text-xs text-muted-foreground">{parsed.extra}</p>
            ) : null}
            {isCriticalDigest && (
              <p className="text-[11px] text-primary/85">
                {locale === "fr" ? "Cliquez sur la reponse pour ouvrir la vue des tickets critiques." : "Click this response to open critical tickets view."}
              </p>
            )}
          </div>
        )
      }
    }
    const blocks = parseAssistantTextBlocks(message.content)
    if (!blocks.length) {
      return <div className="whitespace-pre-wrap">{message.content}</div>
    }
    return (
      <div className="space-y-2.5 break-words text-[13px] leading-6">
        {blocks.map((block, index) => {
          if (block.kind === "list") {
            if (block.ordered) {
              return (
                <ol key={`assistant-block-ordered-${index}`} className="list-decimal space-y-1.5 pl-5 text-foreground/95">
                  {block.items.map((item, itemIndex) => (
                    <li key={`assistant-block-ordered-item-${index}-${itemIndex}`}>{item}</li>
                  ))}
                </ol>
              )
            }
            return (
              <ul key={`assistant-block-bullet-${index}`} className="list-disc space-y-1.5 pl-5 text-foreground/95">
                {block.items.map((item, itemIndex) => (
                  <li key={`assistant-block-bullet-item-${index}-${itemIndex}`}>{item}</li>
                ))}
              </ul>
            )
          }
          const isHeadingLine = block.text.endsWith(":")
          return (
            <p
              key={`assistant-block-paragraph-${index}`}
              className={isHeadingLine ? "font-semibold text-foreground" : "text-foreground/95"}
            >
              {block.text}
            </p>
          )
        })}
      </div>
    )
  }

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, loading])

  useEffect(() => {
    setCriticalOverflowRows([])
    setCriticalOverflowLoaded(false)
    setCriticalOverflowLoading(false)
  }, [locale])

  async function sendMessage(text: string) {
    const normalized = text.trim()
    if (!normalized || loading) return
    const userMessage: ChatMessage = {
      id: `m-${Date.now()}`,
      role: "user",
      content: normalized.slice(0, MAX_CHAT_CONTENT_LEN),
      createdAt: new Date().toISOString(),
    }
    const nextMessages: ChatMessage[] = [...messages, userMessage]
    setMessages(nextMessages)
    setInput("")
    setLoading(true)
    try {
      const payloadMessages = nextMessages
        .slice(-MAX_CHAT_MESSAGES)
        .map((m) => ({ role: m.role, content: m.content.slice(0, MAX_CHAT_CONTENT_LEN) }))
      const result = await apiFetch<{
        reply: string
        message?: string
        action?: string
        ticket?: TicketDraft
        rag_grounding?: boolean
        suggestions?: SuggestionBundle
        draft_context?: DraftContext | null
        actions?: string[]
      }>("/ai/chat", {
        method: "POST",
        body: JSON.stringify({
          messages: payloadMessages,
          locale,
        }),
      })
      const ticketDraft = result.ticket
        ? {
            ...result.ticket,
            description: result.draft_context?.pre_filled_description || result.ticket.description,
          }
        : undefined
      setMessages((prev) => [
        ...prev,
        {
          id: `m-${Date.now()}-bot`,
          role: "assistant",
          content: normalizeAssistantReply(result.message || result.reply, locale),
          createdAt: new Date().toISOString(),
          ticketDraft,
          ticketAction: result.action ?? null,
          ragGrounding: Boolean(result.rag_grounding),
          suggestions: result.suggestions,
          draftContext: result.draft_context ?? null,
          actions: result.actions || [],
        },
      ])
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          id: `m-${Date.now()}-bot`,
          role: "assistant",
          content: getChatErrorMessage(error),
          createdAt: new Date().toISOString(),
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  function handleSend() {
    sendMessage(input)
  }

  function handleQuickPrompt(prompt: string) {
    sendMessage(prompt)
  }

  async function handleCreateTicket(messageId: string, draft: TicketDraft) {
    if (!user) return
    setCreatingId(messageId)
    try {
      const title = (draft.title || "").trim().slice(0, 120)
      const description = (draft.description || "").trim().slice(0, 4000)
      const tags = (draft.tags || []).map((tag) => String(tag || "").trim()).filter(Boolean).slice(0, 10)
      const assignee = (draft.assignee || "").trim() || user.name
      if (title.length < 3 || description.length < 5) {
        throw new Error("invalid_draft_payload")
      }
      const created = await apiFetch<{ id: string }>("/tickets", {
        method: "POST",
        body: JSON.stringify({
          title,
          description,
          priority: draft.priority,
          category: draft.category,
          assignee,
          reporter: user.name,
          tags,
        }),
      })
      setMessages((prev) => [
        ...prev,
        {
          id: `m-${Date.now()}-created`,
          role: "assistant",
          content: `${t("chat.ticketCreated")} ${created.id}`,
          createdAt: new Date().toISOString(),
        },
      ])
      router.push(`/tickets/${created.id}`)
      router.refresh()
    } catch (error) {
      if (error instanceof ApiError) {
        const detail = error.detail || "request_failed"
        setMessages((prev) => [
          ...prev,
          {
            id: `m-${Date.now()}-error`,
            role: "assistant",
            content: `${t("chat.ticketCreateError")} (${detail})`,
            createdAt: new Date().toISOString(),
          },
        ])
        return
      }
      setMessages((prev) => [
        ...prev,
        {
          id: `m-${Date.now()}-error`,
          role: "assistant",
          content: t("chat.ticketCreateError"),
          createdAt: new Date().toISOString(),
        },
      ])
    } finally {
      setCreatingId(null)
    }
  }

  return (
    <Card className="surface-card flex h-[calc(100vh-13rem)] flex-col overflow-hidden rounded-3xl">
      <div className="h-1.5 bg-gradient-to-r from-primary via-emerald-500 to-amber-500" />
      <CardHeader className="shrink-0 border-b border-border/70 pb-3">
        <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/10">
            <Bot className="h-4 w-4 text-primary" />
          </div>
          {t("chat.title")}
        </CardTitle>
        <p className="text-xs text-muted-foreground">{t("chat.subtitle")}</p>
      </CardHeader>

      <CardContent className="flex flex-1 flex-col overflow-hidden p-0">
        <ScrollArea className="flex-1 px-4 py-4 sm:px-5" ref={scrollRef}>
          {messages.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center py-12">
              <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
                <Sparkles className="h-7 w-7 text-primary" />
              </div>
              <h3 className="mb-1 text-base font-semibold text-foreground">{t("chat.howHelp")}</h3>
              <p className="mb-6 max-w-sm text-center text-sm text-muted-foreground">{t("chat.helpDesc")}</p>
              <div className="grid w-full max-w-lg grid-cols-1 gap-2 sm:grid-cols-2">
                {quickPrompts.map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    onClick={() => handleQuickPrompt(prompt)}
                    className="rounded-xl border border-border bg-card/80 p-3 text-left text-xs text-foreground transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:bg-accent/60"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {messages.map((message) => {
                const isUser = message.role === "user"
                const draft = message.ticketDraft
                const parsedDigest = !isUser && message.ticketAction === "show_ticket"
                  ? parseTicketDigest(message.content)
                  : null
                const criticalResponse = Boolean(parsedDigest && isCriticalDigestHeader(parsedDigest.header))
                const showDraftCard = Boolean(draft && message.ticketAction === "create_ticket")
                const canCreate = showDraftCard && hasPermission("create_ticket")
                const timestamp = formatMessageTime(message.createdAt, locale)

                return (
                  <div key={message.id} className="space-y-2">
                    <div className={`flex gap-3 ${isUser ? "justify-end" : "justify-start"}`}>
                      {!isUser && (
                        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10">
                          <Bot className="h-3.5 w-3.5 text-primary" />
                        </div>
                      )}

                      <div className={`flex max-w-[88%] flex-col sm:max-w-[82%] ${isUser ? "items-end" : "items-start"}`}>
                        <div
                          className={`break-words rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed shadow-sm ${
                            isUser
                              ? "bg-gradient-to-br from-primary to-emerald-700 text-primary-foreground"
                              : `border border-border/70 bg-gradient-to-br from-card via-card to-muted/30 text-foreground ${criticalResponse ? "cursor-pointer hover:border-primary/40 hover:bg-card" : ""}`
                          }`}
                          onClick={() => {
                            if (criticalResponse) {
                              router.push("/tickets?view=critical")
                            }
                          }}
                          role={criticalResponse ? "button" : undefined}
                          tabIndex={criticalResponse ? 0 : undefined}
                          onKeyDown={(event) => {
                            if (!criticalResponse) return
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault()
                              router.push("/tickets?view=critical")
                            }
                          }}
                        >
                          {renderAssistantMessage(message)}
                        </div>
                        {timestamp && (
                          <p className="mt-1 px-1 text-[10px] text-muted-foreground">{timestamp}</p>
                        )}
                        {!isUser && hasSuggestions(message.suggestions) && (
                          <div className="mt-2 w-full space-y-2 rounded-xl border border-border/70 bg-card/80 p-2.5">
                            <div className="flex flex-wrap items-center gap-2">
                              <Badge variant="outline" className="text-[10px]">
                                {message.ragGrounding ? "RAG grounded" : "Related suggestions"}
                              </Badge>
                              {message.suggestions?.confidence !== undefined && (
                                <Badge variant="outline" className="text-[10px]">
                                  Confidence {Math.round((message.suggestions.confidence || 0) * 100)}%
                                </Badge>
                              )}
                              {message.suggestions?.tickets?.length ? (
                                <div className="flex flex-wrap gap-1.5">
                                  {message.suggestions.tickets.slice(0, 3).map((row) => (
                                    <HoverCard key={`chip-${message.id}-${row.id}`} openDelay={80} closeDelay={80}>
                                      <HoverCardTrigger asChild>
                                        <button
                                          type="button"
                                          className="rounded-full border border-border bg-background px-2 py-0.5 text-[10px] text-foreground hover:border-primary/50"
                                          onClick={() => router.push(`/tickets/${row.id}`)}
                                        >
                                          #{row.id}
                                        </button>
                                      </HoverCardTrigger>
                                      <HoverCardContent className="w-80 space-y-1 p-3">
                                        <p className="text-xs font-semibold">{row.title}</p>
                                        <p className="text-xs text-muted-foreground">{row.resolution_snippet || "No resolution snippet available."}</p>
                                      </HoverCardContent>
                                    </HoverCard>
                                  ))}
                                </div>
                              ) : null}
                            </div>

                            {message.suggestions?.tickets?.slice(0, 2).map((row) => (
                              <div key={`ticket-sug-${message.id}-${row.id}`} className="rounded-lg border border-border bg-background/70 p-2.5">
                                <div className="flex items-center justify-between gap-2">
                                  <div className="min-w-0">
                                    <p className="truncate text-xs font-semibold text-foreground">
                                      <Lightbulb className="mr-1 inline h-3.5 w-3.5 text-amber-500" />
                                      {row.id} - {row.title}
                                    </p>
                                    <p className="mt-1 text-[11px] text-muted-foreground">{row.resolution_snippet || "No resolution summary."}</p>
                                  </div>
                                  <div className="flex shrink-0 gap-1.5">
                                    <Button type="button" size="sm" variant="outline" className="h-7 px-2 text-[10px]" onClick={() => router.push(`/tickets/${row.id}`)}>
                                      Open
                                    </Button>
                                    {row.resolution_snippet ? (
                                      <Button
                                        type="button"
                                        size="sm"
                                        className="h-7 px-2 text-[10px]"
                                        onClick={() => handleApplySuggestion(message.id, row.resolution_snippet || "", row.id)}
                                      >
                                        Apply
                                      </Button>
                                    ) : null}
                                  </div>
                                </div>
                              </div>
                            ))}

                            {(message.suggestions?.solution_recommendations || []).slice(0, 2).map((rec, idx) => {
                              const userQuery = [...messages].reverse().find((m) => m.role === "user")?.content || ""
                              const upKey = `${message.id}-${rec.source}-${rec.source_id || rec.text.slice(0, 24)}-helpful`
                              const downKey = `${message.id}-${rec.source}-${rec.source_id || rec.text.slice(0, 24)}-not_helpful`
                              return (
                                <div key={`solution-rec-${message.id}-${idx}`} className="rounded-lg border border-border bg-background/70 p-2.5">
                                  <p className="text-xs font-semibold text-foreground">
                                    <Lightbulb className="mr-1 inline h-3.5 w-3.5 text-amber-500" />
                                    {locale === "fr" ? "Recommendation de solution" : "Solution recommendation"}
                                  </p>
                                  <p className="mt-1 text-[11px] text-muted-foreground">{rec.text}</p>
                                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                                    <Badge variant="outline" className="text-[10px]">{rec.source}</Badge>
                                    <Badge variant="outline" className="text-[10px]">Q {Math.round((rec.quality_score || 0) * 100)}%</Badge>
                                    <Badge variant="outline" className="text-[10px]">C {Math.round((rec.confidence || 0) * 100)}%</Badge>
                                    <Badge variant="outline" className="text-[10px]">
                                      {rec.helpful_votes || 0} / {rec.not_helpful_votes || 0}
                                    </Badge>
                                  </div>
                                  <div className="mt-2 flex gap-1.5">
                                    <Button
                                      type="button"
                                      size="sm"
                                      variant="outline"
                                      className="h-7 px-2 text-[10px]"
                                      disabled={feedbackSubmitting[upKey]}
                                      onClick={() => submitSolutionFeedback(message.id, rec, "helpful", userQuery)}
                                    >
                                      <ThumbsUp className="mr-1 h-3.5 w-3.5" />
                                      Helpful
                                    </Button>
                                    <Button
                                      type="button"
                                      size="sm"
                                      variant="outline"
                                      className="h-7 px-2 text-[10px]"
                                      disabled={feedbackSubmitting[downKey]}
                                      onClick={() => submitSolutionFeedback(message.id, rec, "not_helpful", userQuery)}
                                    >
                                      <ThumbsDown className="mr-1 h-3.5 w-3.5" />
                                      Not helpful
                                    </Button>
                                    <Button
                                      type="button"
                                      size="sm"
                                      className="h-7 px-2 text-[10px]"
                                      onClick={() => handleApplySuggestion(message.id, rec.text, rec.source_id || rec.source)}
                                    >
                                      Apply
                                    </Button>
                                  </div>
                                </div>
                              )
                            })}

                            {message.suggestions?.problems?.slice(0, 1).map((problem) => (
                              <div key={`problem-sug-${message.id}-${problem.id}`} className="rounded-lg border border-border bg-background/70 p-2.5">
                                <p className="text-xs font-semibold text-foreground">
                                  <AlertCircle className="mr-1 inline h-3.5 w-3.5 text-orange-500" />
                                  {problem.id} - {problem.title}
                                </p>
                                <p className="mt-1 text-[11px] text-muted-foreground">{problem.match_reason}</p>
                                <div className="mt-2">
                                  <Button type="button" size="sm" variant="outline" className="h-7 px-2 text-[10px]" onClick={() => router.push("/problems")}>
                                    View Problem
                                  </Button>
                                </div>
                              </div>
                            ))}

                            {message.suggestions?.kb_articles?.slice(0, 1).map((kb) => (
                              <div key={`kb-sug-${message.id}-${kb.id}`} className="rounded-lg border border-border bg-background/70 p-2.5">
                                <p className="text-xs font-semibold text-foreground">
                                  <BookOpen className="mr-1 inline h-3.5 w-3.5 text-blue-500" />
                                  {kb.title}
                                </p>
                                <p className="mt-1 text-[11px] text-muted-foreground">{kb.excerpt}</p>
                                <div className="mt-2 flex gap-1.5">
                                  <Button type="button" size="sm" variant="outline" className="h-7 px-2 text-[10px]" onClick={() => setInput(`Use this KB guidance: ${kb.excerpt}`)}>
                                    Use This Solution
                                  </Button>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>

                      {isUser && (
                        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-foreground/10">
                          <User className="h-3.5 w-3.5 text-foreground" />
                        </div>
                      )}
                    </div>

                    {showDraftCard && draft && (
                      <div className={`${isUser ? "mr-10 ml-auto" : "ml-10"} w-full max-w-2xl rounded-2xl border border-border/80 bg-card/90 p-4 shadow-sm`}>
                        <div className="mb-3 flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <Ticket className="h-4 w-4 text-primary" />
                            <span className="text-sm font-semibold text-foreground">{t("chat.ticketDraft")}</span>
                          </div>
                          {!canCreate && (
                            <Badge variant="outline" className="border-border bg-muted/60 text-[10px]">
                              Preview
                            </Badge>
                          )}
                        </div>
                        <div className="space-y-3">
                          <div className="rounded-lg border border-border bg-background/60 p-2.5">
                            <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                              {t("chat.ticketTitle")}
                            </p>
                            <p className="text-sm font-medium text-foreground">{draft.title}</p>
                          </div>
                          <div className="rounded-lg border border-border bg-background/60 p-2.5">
                            <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                              {t("chat.ticketDescription")}
                            </p>
                            <p className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
                              {draft.description}
                            </p>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <Badge variant="outline" className={`text-[10px] ${priorityBadgeClass(t(`priority.${draft.priority}` as "priority.medium"))}`}>
                              {t(`priority.${draft.priority}` as "priority.medium")}
                            </Badge>
                            <Badge variant="outline" className="border-border bg-muted/60 text-[10px]">
                              {t(`category.${draft.category}` as "category.service_request")}
                            </Badge>
                            {draft.assignee && (
                              <Badge variant="outline" className="border-border bg-muted/60 text-[10px]">
                                {t("chat.ticketAssignee")}: {draft.assignee}
                              </Badge>
                            )}
                          </div>
                          {draft.tags.length > 0 && (
                            <div>
                              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                                {t("chat.ticketTags")}
                              </p>
                              <div className="flex flex-wrap gap-1.5">
                                {draft.tags.map((tag) => (
                                  <Badge key={tag} variant="secondary" className="text-[10px]">
                                    {tag}
                                  </Badge>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                        {message.ticketAction === "create_ticket" && !hasPermission("create_ticket") && (
                          <p className="mt-3 text-xs text-muted-foreground">
                            {locale === "fr"
                              ? "Vous pouvez previsualiser le brouillon, mais votre role ne peut pas creer de ticket."
                              : "You can preview this draft, but your role cannot create tickets."}
                          </p>
                        )}
                        {canCreate && (
                          <div className="mt-3">
                            <Button
                              type="button"
                              size="sm"
                              className="h-9 gap-2 rounded-xl"
                              disabled={creatingId === message.id}
                              onClick={() => handleCreateTicket(message.id, draft)}
                            >
                              {creatingId === message.id ? (
                                <RotateCcw className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <CheckCircle2 className="h-3.5 w-3.5" />
                              )}
                              {t("chat.createTicket")}
                            </Button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}

              {loading && (
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10">
                    <Bot className="h-3.5 w-3.5 text-primary" />
                  </div>
                  <div className="rounded-2xl border border-border/70 bg-card/90 px-3.5 py-2.5">
                    <div className="flex items-center gap-1.5">
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary/60" />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary/60 [animation-delay:0.1s]" />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary/60 [animation-delay:0.2s]" />
                      <span className="ml-1 text-[10px] text-muted-foreground">
                        {locale === "fr" ? "Assistant en train d'ecrire..." : "Assistant is typing..."}
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </ScrollArea>

        <div className="shrink-0 border-t border-border/70 bg-card/75 p-3">
          <div className="flex items-center gap-2">
            {messages.length > 0 && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setMessages([])}
                className="h-9 w-9 shrink-0 rounded-xl p-0"
              >
                <RotateCcw className="h-4 w-4" />
                <span className="sr-only">{t("chat.reset")}</span>
              </Button>
            )}
            <Input
              placeholder={t("chat.placeholder")}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              disabled={loading}
              className="h-10 flex-1 rounded-xl bg-background/80"
            />
            <Button
              type="button"
              onClick={handleSend}
              disabled={!input.trim() || loading}
              size="sm"
              className="h-10 w-10 shrink-0 rounded-xl bg-primary p-0 text-primary-foreground hover:bg-primary/90"
            >
              <Send className="h-4 w-4" />
              <span className="sr-only">{t("chat.send")}</span>
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
