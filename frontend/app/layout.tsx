import React from "react"
import type { Metadata } from "next"
import { DM_Sans, DM_Mono, Space_Grotesk } from "next/font/google"
import { Providers } from "@/components/providers"

import "./globals.css"

const _manrope = DM_Sans({ subsets: ["latin"], variable: "--font-manrope" })
const _display = Space_Grotesk({ subsets: ["latin"], variable: "--font-display" })
const _spaceMono = DM_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-space-mono",
})

export const metadata: Metadata = {
  title: "Teamwil Consulting - Ticket Management",
  description:
    "Plateforme intelligente de gestion des tickets avec IA pour Teamwil Consulting",
  icons: {
    icon: "/logo.png",
  },
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="fr" suppressHydrationWarning>
      <body className={`${_manrope.variable} ${_display.variable} ${_spaceMono.variable} font-sans antialiased`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
