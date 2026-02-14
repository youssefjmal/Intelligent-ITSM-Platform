"use client"

import Link from "next/link"
import { AppShell } from "@/components/app-shell"
import { Button } from "@/components/ui/button"

export default function ForbiddenPage() {
  return (
    <AppShell>
      <div className="flex h-[60vh] flex-col items-center justify-center gap-4 text-center">
        <h1 className="text-3xl font-bold text-foreground">403</h1>
        <p className="text-sm text-muted-foreground">
          You do not have permission to access this page.
        </p>
        <Link href="/">
          <Button variant="outline">Back to dashboard</Button>
        </Link>
      </div>
    </AppShell>
  )
}
