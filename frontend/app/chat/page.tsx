"use client"

import React, { useCallback, useEffect, useState } from "react"
import { AppShell } from "@/components/app-shell"
import { AssistantMascot } from "@/components/assistant-mascot"
import { TicketChatbot } from "@/components/ticket-chatbot"
import { useI18n } from "@/lib/i18n"
import { apiFetch } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { MessageSquarePlus, Trash2, MessageSquare, Clock } from "lucide-react"
import { cn } from "@/lib/utils"

interface Conversation {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export default function ChatPage() {
  const { t, locale } = useI18n()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeConvId, setActiveConvId] = useState<string | null>(null)
  const [loadingConvs, setLoadingConvs] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [conversationError, setConversationError] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const loadConversations = useCallback(async () => {
    setLoadingConvs(true)
    setConversationError(null)
    try {
      const data = await apiFetch<Conversation[]>("/ai/conversations?limit=50")
      setConversations(data)
    } catch {
      setConversations([])
      setConversationError(
        locale === "fr"
          ? "Impossible de charger l'historique pour le moment."
          : "Unable to load conversation history right now.",
      )
    } finally {
      setLoadingConvs(false)
    }
  }, [locale])

  useEffect(() => {
    loadConversations()
  }, [loadConversations])

  const handleNewChat = () => {
    setActiveConvId(null)
    setDeleteError(null)
  }

  const handleDeleteConversation = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setDeletingId(id)
    setDeleteError(null)
    try {
      await apiFetch(`/ai/conversations/${id}`, { method: "DELETE" })
      setConversations((prev) => prev.filter((c) => c.id !== id))
      if (activeConvId === id) setActiveConvId(null)
    } catch {
      setDeleteError(
        locale === "fr"
          ? "Suppression impossible pour cette conversation."
          : "Unable to delete that conversation.",
      )
    } finally {
      setDeletingId(null)
    }
  }

  const onConversationSaved = useCallback((id: string) => {
    setActiveConvId(id)
    setDeleteError(null)
    loadConversations()
  }, [loadConversations])

  const formatDate = (iso: string) => {
    const d = new Date(iso)
    const now = new Date()
    const diffDays = Math.floor((now.getTime() - d.getTime()) / 86_400_000)
    if (diffDays === 0) return locale === "fr" ? "Aujourd'hui" : "Today"
    if (diffDays === 1) return locale === "fr" ? "Hier" : "Yesterday"
    return d.toLocaleDateString(locale === "fr" ? "fr-FR" : "en-GB", { day: "numeric", month: "short" })
  }

  return (
    <AppShell>
      <div className="page-shell fade-slide-in mx-auto max-w-7xl">
        <div className="page-hero">
          <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="section-caption">{t("nav.chat")}</p>
              <h2 className="mt-2 text-3xl font-bold text-foreground text-balance sm:text-4xl">
                {t("chat.title")}
              </h2>
              <p className="mt-2 max-w-3xl text-sm text-muted-foreground sm:text-base">
                {t("chat.subtitle")}
              </p>
            </div>
            <div className="flex items-center gap-4 rounded-3xl border border-border/70 bg-background/70 px-4 py-3 shadow-sm backdrop-blur">
              <AssistantMascot locale={locale} speaking className="shrink-0" />
              <div className="max-w-xs">
                <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-primary/80">
                  {locale === "fr" ? "Presence assistant" : "Assistant presence"}
                </p>
                <p className="mt-1 text-sm text-foreground">
                  {locale === "fr"
                    ? "Le copilote garde l'historique de vos conversations."
                    : "The copilot keeps a history of your conversations."}
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className="mt-6 flex gap-4">
          <aside className="hidden w-64 shrink-0 flex-col gap-2 lg:flex">
            <Button
              variant="outline"
              size="sm"
              className="flex w-full items-center gap-2 border-primary/30 text-primary hover:bg-primary/5"
              onClick={handleNewChat}
            >
              <MessageSquarePlus className="h-4 w-4" />
              {locale === "fr" ? "Nouvelle conversation" : "New conversation"}
            </Button>

            <div className="rounded-xl border border-border/70 bg-card/60 backdrop-blur">
              <p className="px-3 pt-3 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
                {locale === "fr" ? "Historique" : "History"}
              </p>
              {conversationError ? (
                <p className="px-3 pt-2 text-[11px] text-destructive">{conversationError}</p>
              ) : null}
              {deleteError ? (
                <p className="px-3 pt-1 text-[11px] text-destructive">{deleteError}</p>
              ) : null}

              {loadingConvs ? (
                <div className="px-3 py-6 text-center text-xs text-muted-foreground">
                  {locale === "fr" ? "Chargement..." : "Loading..."}
                </div>
              ) : conversations.length === 0 ? (
                <div className="flex flex-col items-center gap-2 px-3 py-8 text-center text-muted-foreground">
                  <MessageSquare className="h-8 w-8 opacity-20" />
                  <p className="text-xs">
                    {locale === "fr" ? "Aucune conversation" : "No conversations yet"}
                  </p>
                </div>
              ) : (
                <ScrollArea className="h-[calc(100vh-22rem)]">
                  <div className="space-y-0.5 p-2">
                    {conversations.map((conv) => (
                      <button
                        key={conv.id}
                        type="button"
                        onClick={() => {
                          setActiveConvId(conv.id)
                          setDeleteError(null)
                        }}
                        className={cn(
                          "group relative flex w-full flex-col gap-0.5 rounded-lg px-3 py-2 text-left transition-colors hover:bg-accent/60",
                          activeConvId === conv.id && "bg-primary/10 ring-1 ring-primary/20",
                        )}
                      >
                        <span className="line-clamp-2 text-[12px] font-medium leading-snug text-foreground">
                          {conv.title}
                        </span>
                        <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
                          <Clock className="h-2.5 w-2.5" />
                          {formatDate(conv.updated_at)}
                          <span className="ml-auto opacity-60">
                            {conv.message_count} {locale === "fr" ? "msg" : "msg"}
                          </span>
                        </span>
                        <div
                          role="button"
                          tabIndex={0}
                          onClick={(e) => handleDeleteConversation(conv.id, e)}
                          onKeyDown={(e) => e.key === "Enter" && handleDeleteConversation(conv.id, e as unknown as React.MouseEvent)}
                          aria-disabled={deletingId === conv.id}
                          className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
                          aria-label={locale === "fr" ? "Supprimer" : "Delete"}
                        >
                          <Trash2 className="h-3 w-3" />
                        </div>
                      </button>
                    ))}
                  </div>
                </ScrollArea>
              )}
            </div>
          </aside>

          <div className="min-w-0 flex-1">
            <TicketChatbot
              key={activeConvId ?? "new"}
              conversationId={activeConvId}
              onConversationSaved={onConversationSaved}
            />
          </div>
        </div>
      </div>
    </AppShell>
  )
}
