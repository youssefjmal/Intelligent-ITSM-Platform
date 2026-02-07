"use client"

import { AppShell } from "@/components/app-shell"
import { TicketChatbot } from "@/components/ticket-chatbot"

export default function ChatPage() {
  return (
    <AppShell>
      <div className="max-w-4xl mx-auto">
        <TicketChatbot />
      </div>
    </AppShell>
  )
}
