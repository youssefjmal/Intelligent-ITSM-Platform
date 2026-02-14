"use client"

import { useState, useEffect } from "react"
import { AppShell } from "@/components/app-shell"
import { useAuth, type UserRole, type User, type UserSeniority } from "@/lib/auth"
import { useI18n } from "@/lib/i18n"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Shield, Users, Trash2, Mail } from "lucide-react"
import Link from "next/link"
import { apiFetch } from "@/lib/api"

const ROLE_COLORS: Record<UserRole, string> = {
  admin: "bg-red-100 text-red-800",
  agent: "bg-blue-100 text-blue-800",
  user: "bg-emerald-100 text-emerald-800",
  viewer: "bg-slate-100 text-slate-700",
}

const SENIORITY_OPTIONS: UserSeniority[] = ["intern", "junior", "middle", "senior"]

interface EmailRecord {
  to: string
  subject: string
  body: string
  sent_at: string
  kind: string
}

export default function AdminPage() {
  const { user, hasPermission, getAllUsers, updateUserRole, updateUserSeniority, deleteUser } = useAuth()
  const { t, locale } = useI18n()
  const [users, setUsers] = useState<User[]>([])
  const [emails, setEmails] = useState<EmailRecord[]>([])
  const [actionError, setActionError] = useState<string | null>(null)

  useEffect(() => {
    getAllUsers().then(setUsers).catch(() => {})
  }, [getAllUsers])

  useEffect(() => {
    apiFetch<EmailRecord[]>("/emails")
      .then(setEmails)
      .catch(() => {})
  }, [])

  if (!hasPermission("view_admin")) {
    return (
      <AppShell>
        <div className="flex flex-col items-center justify-center h-[60vh] text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-destructive/10 mb-4">
            <Shield className="h-8 w-8 text-destructive" />
          </div>
          <h2 className="text-xl font-bold text-foreground">{t("admin.accessDenied")}</h2>
          <p className="text-sm text-muted-foreground mt-1">{t("admin.accessDeniedDesc")}</p>
          <Link href="/" className="mt-4">
            <Button variant="outline" className="bg-transparent">
              {t("admin.backToDashboard")}
            </Button>
          </Link>
        </div>
      </AppShell>
    )
  }

  async function handleRoleChange(userId: string, newRole: UserRole) {
    try {
      setActionError(null)
      await updateUserRole(userId, newRole)
      const updated = await getAllUsers()
      setUsers(updated)
    } catch {
      setActionError(
        locale === "fr"
          ? "Echec de mise a jour du role. Verifiez que le backend est accessible."
          : "Failed to update role. Check backend connectivity."
      )
    }
  }

  async function handleSeniorityChange(userId: string, seniorityLevel: UserSeniority) {
    try {
      setActionError(null)
      await updateUserSeniority(userId, seniorityLevel)
      const updated = await getAllUsers()
      setUsers(updated)
    } catch {
      setActionError(
        locale === "fr"
          ? "Echec de mise a jour de la seniorite."
          : "Failed to update seniority."
      )
    }
  }

  async function handleDelete(userId: string) {
    try {
      setActionError(null)
      await deleteUser(userId)
      const updated = await getAllUsers()
      setUsers(updated)
    } catch {
      setActionError(
        locale === "fr"
          ? "Echec de suppression de l'utilisateur."
          : "Failed to delete user."
      )
    }
  }

  return (
    <AppShell>
      <div className="page-shell fade-slide-in">
        <div className="page-hero">
          <p className="section-caption">{t("nav.admin")}</p>
          <h2 className="mt-2 text-3xl font-bold text-foreground text-balance sm:text-4xl">{t("admin.title")}</h2>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground sm:text-base">{t("admin.subtitle")}</p>
          {actionError && <p className="mt-2 text-sm text-destructive">{actionError}</p>}
        </div>

        {/* Users Table */}
        <Card className="surface-card">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
                <Users className="h-5 w-5 text-primary" />
                {t("admin.users")}
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                {users.length} {t("admin.totalUsers")}
              </p>
            </div>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/50 hover:bg-muted/50">
                    <TableHead className="text-foreground font-semibold">{t("admin.name")}</TableHead>
                    <TableHead className="text-foreground font-semibold">{t("admin.email")}</TableHead>
                    <TableHead className="text-foreground font-semibold">{t("admin.role")}</TableHead>
                    <TableHead className="text-foreground font-semibold">{t("admin.seniority")}</TableHead>
                    <TableHead className="text-foreground font-semibold">{t("admin.specializations")}</TableHead>
                    <TableHead className="text-foreground font-semibold">{t("admin.created")}</TableHead>
                    <TableHead className="text-foreground font-semibold text-right">{t("admin.actions")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {users.map((u) => (
                    <TableRow key={u.id} className="hover:bg-muted/30">
                      <TableCell className="font-medium text-foreground">
                        <div className="flex items-center gap-2">
                          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-primary text-xs font-bold shrink-0">
                            {u.name
                              .split(" ")
                              .map((n) => n[0])
                              .join("")
                              .toUpperCase()
                              .slice(0, 2)}
                          </div>
                          <div>
                            <p className="text-sm font-medium text-foreground">{u.name}</p>
                            {user?.id === u.id && (
                              <span className="text-[10px] text-primary font-medium">({t("admin.you")})</span>
                            )}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground font-mono">
                        {u.email}
                      </TableCell>
                      <TableCell>
                        <Select
                          value={u.role}
                          onValueChange={(v) => handleRoleChange(u.id, v as UserRole)}
                          disabled={u.id === user?.id}
                        >
                          <SelectTrigger className="w-36 h-8 text-xs">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="admin">{t("auth.admin")}</SelectItem>
                            <SelectItem value="agent">{t("auth.agent")}</SelectItem>
                            <SelectItem value="user">{t("auth.user")}</SelectItem>
                            <SelectItem value="viewer">{t("auth.viewer")}</SelectItem>
                          </SelectContent>
                        </Select>
                      </TableCell>
                      <TableCell>
                        <Select
                          value={u.seniorityLevel}
                          onValueChange={(v) => handleSeniorityChange(u.id, v as UserSeniority)}
                        >
                          <SelectTrigger className="w-36 h-8 text-xs">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {SENIORITY_OPTIONS.map((level) => (
                              <SelectItem key={`${u.id}-${level}`} value={level}>
                                {t(`seniority.${level}` as "seniority.intern")}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {u.role === "viewer" || u.specializations.length === 0 ? (
                          "-"
                        ) : (
                          <div className="flex flex-wrap gap-1">
                            {u.specializations.map((spec) => (
                              <Badge key={`${u.id}-${spec}`} variant="secondary" className="text-[10px]">
                                {spec.replace(/_/g, " ")}
                              </Badge>
                            ))}
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {new Date(u.createdAt).toLocaleDateString(locale === "fr" ? "fr-FR" : "en-US", {
                          day: "2-digit",
                          month: "short",
                          year: "numeric",
                        })}
                      </TableCell>
                      <TableCell className="text-right">
                        {u.id !== user?.id && (
                          <AlertDialog>
                            <AlertDialogTrigger asChild>
                              <Button variant="ghost" size="sm" className="h-8 w-8 p-0 text-destructive hover:text-destructive">
                                <Trash2 className="h-3.5 w-3.5" />
                                <span className="sr-only">{t("admin.deleteUser")}</span>
                              </Button>
                            </AlertDialogTrigger>
                            <AlertDialogContent>
                              <AlertDialogHeader>
                                <AlertDialogTitle>{t("admin.deleteUser")} {u.name} ?</AlertDialogTitle>
                                <AlertDialogDescription>
                                  {t("admin.deleteConfirm")}
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel>{t("form.cancel")}</AlertDialogCancel>
                                <AlertDialogAction
                                  onClick={() => handleDelete(u.id)}
                                  className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                                >
                                  {t("general.confirm")}
                                </AlertDialogAction>
                              </AlertDialogFooter>
                            </AlertDialogContent>
                          </AlertDialog>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>

        {/* Email Log */}
        <Card className="surface-card">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
              <Mail className="h-5 w-5 text-primary" />
              {t("admin.emailLogTitle")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {emails.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">
                {t("admin.emailLogEmpty")}
              </p>
            ) : (
              <div className="space-y-3">
                {emails.map((em, i) => (
                  <div key={`email-${i}`} className="rounded-lg border border-border p-3 bg-muted/30">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-medium text-foreground">{em.to}</span>
                      <span className="text-xs text-muted-foreground">
                        {new Date(em.sent_at).toLocaleString(locale === "fr" ? "fr-FR" : "en-US")}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground font-medium">{em.subject}</p>
                    <pre className="mt-2 text-[11px] text-muted-foreground whitespace-pre-wrap leading-relaxed bg-background rounded p-2 border border-border max-h-40 overflow-auto">
                      {em.body}
                    </pre>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  )
}
