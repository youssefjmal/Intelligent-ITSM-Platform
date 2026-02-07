"use client"

import React, { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Sparkles, Loader2, X, BrainCircuit } from "lucide-react"
import type { TicketPriority, TicketCategory } from "@/lib/ticket-data"
import { useI18n } from "@/lib/i18n"
import { useAuth } from "@/lib/auth"
import { apiFetch } from "@/lib/api"

type Assignee = {
  id: string
  name: string
  role: string
}

interface AISuggestion {
  priority: TicketPriority
  category: TicketCategory
  recommendations: string[]
}

export function TicketForm() {
  const router = useRouter()
  const { t } = useI18n()
  const { user } = useAuth()
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [priority, setPriority] = useState<TicketPriority>("medium")
  const [category, setCategory] = useState<TicketCategory>("bug")
  const [assignee, setAssignee] = useState("")
  const [assignees, setAssignees] = useState<Assignee[]>([])
  const [tags, setTags] = useState<string[]>([])
  const [tagInput, setTagInput] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [aiLoading, setAiLoading] = useState(false)
  const [aiSuggestion, setAiSuggestion] = useState<AISuggestion | null>(null)

  useEffect(() => {
    let mounted = true
    apiFetch<Assignee[]>("/users/assignees")
      .then((data) => {
        if (!mounted) return
        setAssignees(data)
        setAssignee((current) => current || (data[0]?.name ?? ""))
      })
      .catch(() => {})
    return () => {
      mounted = false
    }
  }, [])

  async function handleAIClassify() {
    if (!title && !description) return
    setAiLoading(true)
    try {
      const data = await apiFetch<{ priority: TicketPriority; category: TicketCategory; recommendations: string[] }>(
        "/ai/classify",
        {
          method: "POST",
          body: JSON.stringify({ title, description }),
        }
      )
      setAiSuggestion(data)
      if (data.priority) setPriority(data.priority)
      if (data.category) setCategory(data.category)
    } catch {
      // fallback silent
    } finally {
      setAiLoading(false)
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    try {
      await apiFetch("/tickets", {
        method: "POST",
        body: JSON.stringify({
          title,
          description,
          priority,
          category,
          assignee,
          reporter: user?.name || "Unknown",
          tags,
        }),
      })
      router.push("/tickets")
      router.refresh()
    } catch {
      // handle error
    } finally {
      setSubmitting(false)
    }
  }

  function addTag() {
    if (tagInput.trim() && !tags.includes(tagInput.trim())) {
      setTags([...tags, tagInput.trim()])
      setTagInput("")
    }
  }

  function removeTag(tag: string) {
    setTags(tags.filter((t) => t !== tag))
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Main Form */}
        <div className="lg:col-span-2 space-y-6">
          <Card className="border border-border">
            <CardHeader className="pb-4">
              <CardTitle className="text-base font-semibold text-foreground">
                Details du Ticket
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="title" className="text-foreground">Titre</Label>
                <Input
                  id="title"
                  placeholder="Decrivez brievement le probleme ou la demande..."
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  required
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="description" className="text-foreground">Description</Label>
                <Textarea
                  id="description"
                  placeholder="Fournissez une description detaillee incluant les etapes de reproduction, l'impact, et le comportement attendu..."
                  rows={6}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  required
                />
              </div>

              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleAIClassify}
                  disabled={aiLoading || (!title && !description)}
                  className="gap-2 bg-transparent"
                >
                  {aiLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Sparkles className="h-4 w-4" />
                  )}
                  Classification IA
                </Button>
                <span className="text-xs text-muted-foreground">
                  L'IA analysera le contenu pour suggerer la priorite et la categorie
                </span>
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label className="text-foreground">Priorite</Label>
                  <Select value={priority} onValueChange={(v) => setPriority(v as TicketPriority)}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="critical">Critique</SelectItem>
                      <SelectItem value="high">Haute</SelectItem>
                      <SelectItem value="medium">Moyenne</SelectItem>
                      <SelectItem value="low">Basse</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label className="text-foreground">Categorie</Label>
                  <Select value={category} onValueChange={(v) => setCategory(v as TicketCategory)}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="bug">Bug</SelectItem>
                      <SelectItem value="feature">Fonctionnalite</SelectItem>
                      <SelectItem value="support">Support</SelectItem>
                      <SelectItem value="infrastructure">Infrastructure</SelectItem>
                      <SelectItem value="security">Securite</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="space-y-2">
                <Label className="text-foreground">Assigner a</Label>
                {assignees.length > 0 ? (
                  <Select value={assignee} onValueChange={setAssignee}>
                    <SelectTrigger>
                      <SelectValue placeholder="Selectionner un membre..." />
                    </SelectTrigger>
                    <SelectContent>
                      {assignees.map((member) => (
                        <SelectItem key={member.id} value={member.name}>
                          {member.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    placeholder="Saisir un assignee..."
                    value={assignee}
                    onChange={(e) => setAssignee(e.target.value)}
                    required
                  />
                )}
              </div>

              <div className="space-y-2">
                <Label className="text-foreground">Tags</Label>
                <div className="flex gap-2">
                  <Input
                    placeholder="Ajouter un tag..."
                    value={tagInput}
                    onChange={(e) => setTagInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault()
                        addTag()
                      }
                    }}
                  />
                  <Button type="button" variant="outline" size="sm" onClick={addTag}>
                    Ajouter
                  </Button>
                </div>
                {tags.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {tags.map((tag) => (
                      <Badge key={tag} variant="secondary" className="gap-1 text-xs">
                        {tag}
                        <button type="button" onClick={() => removeTag(tag)}>
                          <X className="h-3 w-3" />
                        </button>
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          <div className="flex justify-end gap-3">
            <Button type="button" variant="outline" onClick={() => router.back()}>
              Annuler
            </Button>
            <Button
              type="submit"
              disabled={submitting || !title || !description || !assignee}
              className="bg-primary text-primary-foreground hover:bg-primary/90 gap-2"
            >
              {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
              Creer le Ticket
            </Button>
          </div>
        </div>

        {/* AI Suggestions Sidebar */}
        <div className="space-y-4">
          {aiSuggestion && (
            <Card className="border-2 border-primary/20 bg-accent/30">
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  <BrainCircuit className="h-4 w-4 text-primary" />
                  Suggestions IA
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <p className="text-xs font-medium text-muted-foreground mb-1">
                    Priorite suggeree
                  </p>
                  <Badge className="text-xs">
                    {aiSuggestion.priority === "critical"
                      ? "Critique"
                      : aiSuggestion.priority === "high"
                        ? "Haute"
                        : aiSuggestion.priority === "medium"
                          ? "Moyenne"
                          : "Basse"}
                  </Badge>
                </div>
                <div>
                  <p className="text-xs font-medium text-muted-foreground mb-1">
                    Categorie suggeree
                  </p>
                  <Badge variant="secondary" className="text-xs">
                    {aiSuggestion.category === "bug"
                      ? "Bug"
                      : aiSuggestion.category === "feature"
                        ? "Fonctionnalite"
                        : aiSuggestion.category === "support"
                          ? "Support"
                          : aiSuggestion.category === "infrastructure"
                            ? "Infrastructure"
                            : "Securite"}
                  </Badge>
                </div>
                {aiSuggestion.recommendations.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-muted-foreground mb-2">
                      Solutions recommandees
                    </p>
                    <ul className="space-y-2">
                      {aiSuggestion.recommendations.map((rec, i) => (
                        <li
                          key={`rec-${i}`}
                          className="text-xs text-foreground bg-background rounded-md p-2 border border-border"
                        >
                          {rec}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          <Card className="border border-border">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Sparkles className="h-4 w-4 text-primary" />
                Aide IA
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Remplissez le titre et la description, puis cliquez sur
                &quot;Classification IA&quot; pour obtenir des suggestions
                automatiques de priorite, categorie, et des recommandations
                basees sur les tickets precedents.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </form>
  )
}
