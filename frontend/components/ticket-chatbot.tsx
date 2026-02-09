// Simple chat UI that calls the backend AI endpoint.
"use client"

import { useEffect, useRef, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Badge } from "@/components/ui/badge"
import { apiFetch } from "@/lib/api"
import { Send, Bot, User, Sparkles, RotateCcw, Ticket, CheckCircle2 } from "lucide-react"
import { useI18n } from "@/lib/i18n"
import { useAuth } from "@/lib/auth"
import { useRouter } from "next/navigation"

type ChatMessage = {
  id: string
  role: "user" | "assistant"
  content: string
  ticketDraft?: TicketDraft
}

type TicketDraft = {
  title: string
  description: string
  priority: "critical" | "high" | "medium" | "low"
  category: "bug" | "feature" | "support" | "infrastructure" | "security"
  tags: string[]
  assignee?: string | null
}

export function TicketChatbot() {
  const { t, locale } = useI18n()
  const { user } = useAuth()
  const router = useRouter()
  const [input, setInput] = useState("")
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [creatingId, setCreatingId] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  const quickPrompts = [
    t("chat.prompt1"),
    t("chat.prompt2"),
    t("chat.prompt3"),
    t("chat.prompt4"),
  ]

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, loading])

  async function sendMessage(text: string) {
    if (!text.trim() || loading) return
    const userMessage: ChatMessage = {
      id: `m-${Date.now()}`,
      role: "user",
      content: text,
    }
    const nextMessages: ChatMessage[] = [...messages, userMessage]
    setMessages(nextMessages)
    setInput("")
    setLoading(true)
    try {
      const result = await apiFetch<{ reply: string; action?: string; ticket?: TicketDraft }>("/ai/chat", {
        method: "POST",
        body: JSON.stringify({
          messages: nextMessages.map((m) => ({ role: m.role, content: m.content })),
          locale,
        }),
      })
      const ticketDraft = result.action === "create_ticket" ? result.ticket : undefined
      setMessages((prev) => [
        ...prev,
        { id: `m-${Date.now()}-bot`, role: "assistant", content: result.reply, ticketDraft },
      ])
    } catch {
      setMessages((prev) => [
        ...prev,
        { id: `m-${Date.now()}-bot`, role: "assistant", content: t("chat.errorReply") },
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
      const created = await apiFetch<{ id: string }>("/tickets", {
        method: "POST",
        body: JSON.stringify({
          title: draft.title,
          description: draft.description,
          priority: draft.priority,
          category: draft.category,
          assignee: draft.assignee || user.name,
          reporter: user.name,
          tags: draft.tags || [],
        }),
      })
      setMessages((prev) => [
        ...prev,
        {
          id: `m-${Date.now()}-created`,
          role: "assistant",
          content: `${t("chat.ticketCreated")} ${created.id}`,
        },
      ])
      router.push(`/tickets/${created.id}`)
      router.refresh()
    } catch {
      setMessages((prev) => [
        ...prev,
        { id: `m-${Date.now()}-error`, role: "assistant", content: t("chat.ticketCreateError") },
      ])
    } finally {
      setCreatingId(null)
    }
  }

  return (
    <Card className="flex flex-col h-[calc(100vh-10rem)] border border-border">
      <CardHeader className="pb-3 border-b border-border shrink-0">
        <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
            <Bot className="h-4 w-4 text-primary" />
          </div>
          {t("chat.title")}
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          {t("chat.subtitle")}
        </p>
      </CardHeader>

      <CardContent className="flex-1 overflow-hidden p-0 flex flex-col">
        <ScrollArea className="flex-1 p-4" ref={scrollRef}>
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full py-12">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 mb-4">
                <Sparkles className="h-7 w-7 text-primary" />
              </div>
              <h3 className="text-base font-semibold text-foreground mb-1">
                {t("chat.howHelp")}
              </h3>
              <p className="text-sm text-muted-foreground text-center max-w-sm mb-6">
                {t("chat.helpDesc")}
              </p>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 max-w-lg w-full">
                {quickPrompts.map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    onClick={() => handleQuickPrompt(prompt)}
                    className="rounded-lg border border-border bg-card p-3 text-left text-xs text-foreground hover:bg-accent/50 hover:border-primary/30 transition-colors"
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
                return (
                  <div key={message.id} className="space-y-3">
                    <div
                      className={`flex gap-3 ${isUser ? "justify-end" : "justify-start"}`}
                    >
                      {!isUser && (
                        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10">
                          <Bot className="h-3.5 w-3.5 text-primary" />
                        </div>
                      )}
                      <div
                        className={`max-w-[80%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed ${
                          isUser
                            ? "bg-primary text-primary-foreground"
                            : "bg-muted text-foreground"
                        }`}
                      >
                        <div className="whitespace-pre-wrap">{message.content}</div>
                      </div>
                      {isUser && (
                        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-foreground/10">
                          <User className="h-3.5 w-3.5 text-foreground" />
                        </div>
                      )}
                    </div>
                    {draft && (
                      <div className="ml-10 rounded-xl border border-border bg-card p-4">
                    <div className="flex items-center gap-2 mb-3">
                      <Ticket className="h-4 w-4 text-primary" />
                      <span className="text-sm font-semibold text-foreground">{t("chat.ticketDraft")}</span>
                    </div>
                    <div className="space-y-2 text-xs text-muted-foreground">
                      <div>
                        <span className="font-medium text-foreground">{t("chat.ticketTitle")}:</span> {draft.title}
                      </div>
                      <div>
                        <span className="font-medium text-foreground">{t("chat.ticketDescription")}:</span> {draft.description}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Badge variant="secondary" className="text-[10px]">
                          {t(`priority.${draft.priority}` as "priority.medium")}
                        </Badge>
                        <Badge variant="outline" className="text-[10px]">
                          {t(`category.${draft.category}` as "category.support")}
                        </Badge>
                        {draft.assignee && (
                          <Badge variant="outline" className="text-[10px]">
                            {t("chat.ticketAssignee")}: {draft.assignee}
                          </Badge>
                        )}
                      </div>
                      {draft.tags.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          <span className="font-medium text-foreground">{t("chat.ticketTags")}:</span>
                          {draft.tags.map((tag) => (
                            <Badge key={tag} variant="secondary" className="text-[10px]">
                              {tag}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="mt-3">
                      <Button
                        type="button"
                        size="sm"
                        className="gap-2"
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
                      </div>
                    )}
                  </div>
                )
              })}
              {loading && (
                <div className="flex gap-3">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10">
                    <Bot className="h-3.5 w-3.5 text-primary" />
                  </div>
                  <div className="rounded-xl bg-muted px-3.5 py-2.5">
                    <div className="flex gap-1">
                      <span className="h-1.5 w-1.5 rounded-full bg-primary/60 animate-bounce" />
                      <span className="h-1.5 w-1.5 rounded-full bg-primary/60 animate-bounce [animation-delay:0.1s]" />
                      <span className="h-1.5 w-1.5 rounded-full bg-primary/60 animate-bounce [animation-delay:0.2s]" />
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </ScrollArea>

        <div className="shrink-0 border-t border-border p-3">
          <div className="flex items-center gap-2">
            {messages.length > 0 && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setMessages([])}
                className="shrink-0 h-9 w-9 p-0"
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
              className="flex-1"
            />
            <Button
              type="button"
              onClick={handleSend}
              disabled={!input.trim() || loading}
              size="sm"
              className="shrink-0 bg-primary text-primary-foreground hover:bg-primary/90 h-9 w-9 p-0"
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
