"use client"

import { useState, useEffect } from "react"
import { AppShell } from "@/components/app-shell"
import { useAuth, type UserRole, type User } from "@/lib/auth"
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
  viewer: "bg-slate-100 text-slate-700",
}

interface EmailRecord {
  to: string
  subject: string
  body: string
  sent_at: string
  kind: string
}

export default function AdminPage() {
  const { user, hasPermission, getAllUsers, updateUserRole, deleteUser } = useAuth()
  const { t } = useI18n()
  const [users, setUsers] = useState<User[]>([])
  const [emails, setEmails] = useState<EmailRecord[]>([])

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
    await updateUserRole(userId, newRole)
    const updated = await getAllUsers()
    setUsers(updated)
  }

  async function handleDelete(userId: string) {
    await deleteUser(userId)
    const updated = await getAllUsers()
    setUsers(updated)
  }

  return (
    <AppShell>
      <div className="space-y-6">
        <div>
          <h2 className="text-2xl font-bold text-foreground text-balance">{t("admin.title")}</h2>
          <p className="text-sm text-muted-foreground mt-1">{t("admin.subtitle")}</p>
        </div>

        {/* Users Table */}
        <Card className="border border-border">
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
                              <span className="text-[10px] text-primary font-medium">(vous)</span>
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
                            <SelectItem value="viewer">{t("auth.viewer")}</SelectItem>
                          </SelectContent>
                        </Select>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {new Date(u.createdAt).toLocaleDateString("fr-FR", {
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
                                  {"Cette action est irreversible. L'utilisateur sera supprime definitivement."}
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
        <Card className="border border-border">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
              <Mail className="h-5 w-5 text-primary" />
              Emails de bienvenue envoyes
            </CardTitle>
          </CardHeader>
          <CardContent>
            {emails.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">
                Aucun email envoye pour le moment.
              </p>
            ) : (
              <div className="space-y-3">
                {emails.map((em, i) => (
                  <div key={`email-${i}`} className="rounded-lg border border-border p-3 bg-muted/30">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-medium text-foreground">{em.to}</span>
                      <span className="text-xs text-muted-foreground">
                        {new Date(em.sent_at).toLocaleString("fr-FR")}
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
