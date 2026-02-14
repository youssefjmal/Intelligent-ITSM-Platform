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
  assignee?: string | null
}

export function TicketForm() {
  const router = useRouter()
  const { t } = useI18n()
  const { user } = useAuth()
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [priority, setPriority] = useState<TicketPriority>("medium")
  const [category, setCategory] = useState<TicketCategory>("service_request")
  const [assignee, setAssignee] = useState("auto")
  const [assignees, setAssignees] = useState<Assignee[]>([])
  const [tags, setTags] = useState<string[]>([])
  const [tagInput, setTagInput] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [aiLoading, setAiLoading] = useState(false)
  const [aiSuggestion, setAiSuggestion] = useState<AISuggestion | null>(null)
  const trimmedTitle = title.trim()
  const trimmedDescription = description.trim()
  const aiTitle = trimmedTitle.length >= 3 ? trimmedTitle : trimmedDescription
  const aiDescription = trimmedDescription || trimmedTitle
  const canAIClassify = aiTitle.length >= 3 && aiDescription.length > 0

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
    if (!canAIClassify) return
    setAiLoading(true)
    try {
      const data = await apiFetch<{
        priority: TicketPriority
        category: TicketCategory
        recommendations: string[]
        assignee?: string | null
      }>(
        "/ai/classify",
        {
          method: "POST",
          body: JSON.stringify({ title: aiTitle, description: aiDescription }),
        }
      )
      setAiSuggestion(data)
      if (data.priority) setPriority(data.priority)
      if (data.category) setCategory(data.category)
      if (data.assignee) setAssignee(data.assignee)
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
          auto_priority_applied: Boolean(aiSuggestion),
          assignment_model_version: assignee === "auto" ? "smart-v1" : "manual",
          priority_model_version: aiSuggestion ? "smart-v1" : "manual",
          predicted_priority: aiSuggestion?.priority || null,
          predicted_category: aiSuggestion?.category || null,
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
    <form onSubmit={handleSubmit} className="space-y-6 fade-slide-in">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Main Form */}
        <div className="lg:col-span-2 space-y-6">
          <Card className="surface-card overflow-hidden rounded-2xl">
            <div className="h-1.5 bg-gradient-to-r from-primary via-emerald-500 to-amber-500" />
            <CardHeader className="pb-4">
              <CardTitle className="text-base font-semibold text-foreground">
                {t("form.details")}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="title" className="text-foreground">{t("form.title")}</Label>
                <Input
                  id="title"
                  placeholder={t("form.titlePlaceholder")}
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  required
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="description" className="text-foreground">{t("form.description")}</Label>
                <Textarea
                  id="description"
                  placeholder={t("form.descPlaceholder")}
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
                  disabled={aiLoading || !canAIClassify}
                  className="gap-2 bg-card/80"
                >
                  {aiLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Sparkles className="h-4 w-4" />
                  )}
                  {t("form.aiClassify")}
                </Button>
                <span className="text-xs text-muted-foreground">
                  {t("form.aiClassifyDesc")}
                </span>
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label className="text-foreground">{t("form.priority")}</Label>
                  <Select value={priority} onValueChange={(v) => setPriority(v as TicketPriority)}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="critical">{t("priority.critical")}</SelectItem>
                      <SelectItem value="high">{t("priority.high")}</SelectItem>
                      <SelectItem value="medium">{t("priority.medium")}</SelectItem>
                      <SelectItem value="low">{t("priority.low")}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label className="text-foreground">{t("form.category")}</Label>
                  <Select value={category} onValueChange={(v) => setCategory(v as TicketCategory)}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="infrastructure">{t("category.infrastructure")}</SelectItem>
                      <SelectItem value="network">{t("category.network")}</SelectItem>
                      <SelectItem value="security">{t("category.security")}</SelectItem>
                      <SelectItem value="application">{t("category.application")}</SelectItem>
                      <SelectItem value="service_request">{t("category.service_request")}</SelectItem>
                      <SelectItem value="hardware">{t("category.hardware")}</SelectItem>
                      <SelectItem value="email">{t("category.email")}</SelectItem>
                      <SelectItem value="problem">{t("category.problem")}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="space-y-2">
                <Label className="text-foreground">{t("form.assignTo")}</Label>
                {assignees.length > 0 ? (
                  <Select value={assignee} onValueChange={setAssignee}>
                    <SelectTrigger>
                      <SelectValue placeholder={t("form.assignPlaceholder")} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="auto">{t("form.autoAssign")}</SelectItem>
                      {assignees.map((member) => (
                        <SelectItem key={member.id} value={member.name}>
                          {member.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    placeholder={t("form.assigneeManualPlaceholder")}
                    value={assignee}
                    onChange={(e) => setAssignee(e.target.value)}
                    required
                  />
                )}
              </div>

              <div className="space-y-2">
                <Label className="text-foreground">{t("form.tags")}</Label>
                <div className="flex gap-2">
                  <Input
                    placeholder={t("form.addTag")}
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
                    {t("form.add")}
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
              {t("form.cancel")}
            </Button>
            <Button
              type="submit"
              disabled={submitting || !title || !description || !assignee}
              className="bg-primary text-primary-foreground hover:bg-primary/90 gap-2"
            >
              {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
              {t("form.create")}
            </Button>
          </div>
        </div>

        {/* AI Suggestions Sidebar */}
        <div className="space-y-4">
          {aiSuggestion && (
            <Card className="overflow-hidden rounded-2xl border-2 border-primary/20 bg-accent/30 shadow-sm">
            <div className="h-1.5 bg-gradient-to-r from-primary via-emerald-500 to-amber-500" />
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <BrainCircuit className="h-4 w-4 text-primary" />
                {t("form.aiSuggestions")}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <p className="text-xs font-medium text-muted-foreground mb-1">
                  {t("form.suggestedPriority")}
                </p>
                <Badge className="text-xs">
                  {aiSuggestion.priority === "critical"
                    ? t("priority.critical")
                    : aiSuggestion.priority === "high"
                      ? t("priority.high")
                      : aiSuggestion.priority === "medium"
                        ? t("priority.medium")
                        : t("priority.low")}
                </Badge>
              </div>
              <div>
                <p className="text-xs font-medium text-muted-foreground mb-1">
                  {t("form.suggestedCategory")}
                </p>
                <Badge variant="secondary" className="text-xs">
                  {aiSuggestion.category === "infrastructure"
                    ? t("category.infrastructure")
                    : aiSuggestion.category === "network"
                      ? t("category.network")
                      : aiSuggestion.category === "security"
                        ? t("category.security")
                        : aiSuggestion.category === "application"
                          ? t("category.application")
                          : aiSuggestion.category === "service_request"
                            ? t("category.service_request")
                            : aiSuggestion.category === "hardware"
                              ? t("category.hardware")
                              : aiSuggestion.category === "email"
                                ? t("category.email")
                                : t("category.problem")}
                </Badge>
              </div>
              {aiSuggestion.assignee && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground mb-1">
                    {t("form.suggestedAssignee")}
                  </p>
                  <Badge variant="outline" className="text-xs">
                    {aiSuggestion.assignee}
                  </Badge>
                </div>
              )}
              {aiSuggestion.recommendations.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground mb-2">
                    {t("form.recommendedSolutions")}
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

          <Card className="surface-card">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Sparkles className="h-4 w-4 text-primary" />
                {t("form.aiHelp")}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground leading-relaxed">
                {t("form.aiHelpDesc")}
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </form>
  )
}
