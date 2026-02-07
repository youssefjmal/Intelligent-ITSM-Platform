// Simple chat UI that calls the backend AI endpoint.
"use client"

import { useEffect, useRef, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { apiFetch } from "@/lib/api"
import { Send, Bot, User, Sparkles, RotateCcw } from "lucide-react"

type ChatMessage = {
  id: string
  role: "user" | "assistant"
  content: string
}

const QUICK_PROMPTS = [
  "Quels sont les tickets critiques en cours ?",
  "Resume l'activite de la semaine",
  "Quels tickets sont en attente depuis longtemps ?",
  "Recommande des solutions pour les bugs recurrents",
]

export function TicketChatbot() {
  const [input, setInput] = useState("")
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, loading])

  async function sendMessage(text: string) {
    if (!text.trim() || loading) return
    const nextMessages = [...messages, { id: `m-${Date.now()}`, role: "user", content: text }]
    setMessages(nextMessages)
    setInput("")
    setLoading(true)
    try {
      const result = await apiFetch<{ reply: string }>("/ai/chat", {
        method: "POST",
        body: JSON.stringify({
          messages: nextMessages.map((m) => ({ role: m.role, content: m.content })),
        }),
      })
      setMessages((prev) => [
        ...prev,
        { id: `m-${Date.now()}-bot`, role: "assistant", content: result.reply },
      ])
    } catch {
      setMessages((prev) => [
        ...prev,
        { id: `m-${Date.now()}-bot`, role: "assistant", content: "Une erreur est survenue." },
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

  return (
    <Card className="flex flex-col h-[calc(100vh-10rem)] border border-border">
      <CardHeader className="pb-3 border-b border-border shrink-0">
        <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
            <Bot className="h-4 w-4 text-primary" />
          </div>
          Assistant IA - TeamWill
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          Posez vos questions sur les tickets, obtenez des recommandations et des analyses en temps reel.
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
                Comment puis-je vous aider ?
              </h3>
              <p className="text-sm text-muted-foreground text-center max-w-sm mb-6">
                Je peux analyser vos tickets, recommander des solutions et vous aider a prioriser votre travail.
              </p>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 max-w-lg w-full">
                {QUICK_PROMPTS.map((prompt) => (
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
                return (
                  <div
                    key={message.id}
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
                <span className="sr-only">Reinitialiser</span>
              </Button>
            )}
            <Input
              placeholder="Posez une question sur vos tickets..."
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
              <span className="sr-only">Envoyer</span>
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
