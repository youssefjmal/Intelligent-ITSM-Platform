"use client"

import React from "react"

import { useState } from "react"
import Link from "next/link"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  ArrowLeft,
  Calendar,
  User,
  Tag,
  MessageSquare,
  Clock,
  CheckCircle2,
} from "lucide-react"
import {
  type Ticket,
  type TicketStatus,
  STATUS_CONFIG,
  PRIORITY_CONFIG,
  CATEGORY_CONFIG,
} from "@/lib/ticket-data"
import { apiFetch } from "@/lib/api"

interface TicketDetailProps {
  ticket: Ticket
}

export function TicketDetail({ ticket }: TicketDetailProps) {
  const [status, setStatus] = useState<TicketStatus>(ticket.status)
  const [updating, setUpdating] = useState(false)

  async function handleStatusChange(newStatus: string) {
    setUpdating(true)
    try {
      await apiFetch(`/tickets/${ticket.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: newStatus }),
      })
      setStatus(newStatus as TicketStatus)
    } catch {
      // silent
    } finally {
      setUpdating(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/tickets">
          <Button variant="ghost" size="sm" className="gap-1.5">
            <ArrowLeft className="h-4 w-4" />
            Retour
          </Button>
        </Link>
        <span className="text-sm font-mono text-muted-foreground">{ticket.id}</span>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Main Content */}
        <div className="lg:col-span-2 space-y-6">
          <Card className="border border-border">
            <CardHeader>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="space-y-1">
                  <CardTitle className="text-xl font-bold text-foreground">
                    {ticket.title}
                  </CardTitle>
                  <p className="text-sm text-muted-foreground">
                    Signale par {ticket.reporter} le{" "}
                    {new Date(ticket.createdAt).toLocaleDateString("fr-FR", {
                      day: "2-digit",
                      month: "long",
                      year: "numeric",
                    })}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge className={`${PRIORITY_CONFIG[ticket.priority].color} border-0`}>
                    {PRIORITY_CONFIG[ticket.priority].label}
                  </Badge>
                  <Badge className={`${STATUS_CONFIG[status].color} border-0`}>
                    {STATUS_CONFIG[status].label}
                  </Badge>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-6">
              <div>
                <h3 className="text-sm font-semibold text-foreground mb-2">Description</h3>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  {ticket.description}
                </p>
              </div>

              {ticket.resolution && (
                <div className="rounded-lg bg-accent/50 p-4 border border-primary/20">
                  <div className="flex items-center gap-2 mb-2">
                    <CheckCircle2 className="h-4 w-4 text-primary" />
                    <h3 className="text-sm font-semibold text-foreground">Resolution</h3>
                  </div>
                  <p className="text-sm text-foreground/80 leading-relaxed">
                    {ticket.resolution}
                  </p>
                </div>
              )}

              <Separator />

              {/* Comments */}
              <div>
                <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground mb-4">
                  <MessageSquare className="h-4 w-4" />
                  Commentaires ({ticket.comments.length})
                </h3>
                {ticket.comments.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Aucun commentaire</p>
                ) : (
                  <div className="space-y-3">
                    {ticket.comments.map((comment) => (
                      <div
                        key={comment.id}
                        className="rounded-lg border border-border p-3 bg-muted/30"
                      >
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="text-sm font-medium text-foreground">
                            {comment.author}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {new Date(comment.createdAt).toLocaleDateString("fr-FR", {
                              day: "2-digit",
                              month: "short",
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
                          </span>
                        </div>
                        <p className="text-sm text-muted-foreground">{comment.content}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Sidebar Info */}
        <div className="space-y-4">
          <Card className="border border-border">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold text-foreground">
                Informations
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">Statut</p>
                <Select
                  value={status}
                  onValueChange={handleStatusChange}
                  disabled={updating}
                >
                  <SelectTrigger className="h-8 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(STATUS_CONFIG).map(([key, val]) => (
                      <SelectItem key={key} value={key}>
                        {val.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <Separator />

              <InfoRow icon={User} label="Assigne a" value={ticket.assignee} />
              <InfoRow icon={User} label="Signale par" value={ticket.reporter} />
              <InfoRow
                icon={Tag}
                label="Categorie"
                value={CATEGORY_CONFIG[ticket.category].label}
              />
              <InfoRow
                icon={Calendar}
                label="Cree le"
                value={new Date(ticket.createdAt).toLocaleDateString("fr-FR")}
              />
              <InfoRow
                icon={Clock}
                label="Mis a jour"
                value={new Date(ticket.updatedAt).toLocaleDateString("fr-FR")}
              />

              {ticket.tags.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground mb-1.5">Tags</p>
                  <div className="flex flex-wrap gap-1">
                    {ticket.tags.map((tag) => (
                      <Badge key={tag} variant="secondary" className="text-[10px]">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

function InfoRow({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: string
}) {
  return (
    <div className="flex items-start gap-2">
      <Icon className="mt-0.5 h-3.5 w-3.5 text-muted-foreground" />
      <div>
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        <p className="text-sm text-foreground">{value}</p>
      </div>
    </div>
  )
}
