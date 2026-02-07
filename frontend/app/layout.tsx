import React from "react"
import type { Metadata } from "next"
import { Inter, Space_Mono } from "next/font/google"
import { Providers } from "@/components/providers"

import "./globals.css"

const _inter = Inter({ subsets: ["latin"], variable: "--font-inter" })
const _spaceMono = Space_Mono({
  subsets: ["latin"],
  weight: ["400", "700"],
  variable: "--font-space-mono",
})

export const metadata: Metadata = {
  title: "TeamWill Consulting - Ticket Management",
  description:
    "Plateforme intelligente de gestion des tickets avec IA pour TeamWill Consulting",
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="fr">
      <body className="font-sans antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
