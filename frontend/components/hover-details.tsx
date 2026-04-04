"use client"

import { createPortal } from "react-dom"
import { useMemo, useState, type ReactNode } from "react"
import { cn } from "@/lib/utils"

export type HoverDetailRow = {
  label: string
  value: string
}

type HoverDetailsProps = {
  title: string
  details?: HoverDetailRow[]
  note?: string
  children: ReactNode
  className?: string
  panelClassName?: string
  disabled?: boolean
}

export function HoverDetails({
  title,
  details = [],
  note,
  children,
  className,
  panelClassName,
  disabled = false,
}: HoverDetailsProps) {
  const [hovered, setHovered] = useState(false)
  const [pointer, setPointer] = useState({ x: 0, y: 0 })

  const popupStyle = useMemo(() => {
    if (typeof window === "undefined") {
      return { left: pointer.x, top: pointer.y }
    }
    const maxLeft = Math.max(24, window.innerWidth - 320)
    const maxTop = Math.max(24, window.innerHeight - 240)
    return {
      left: Math.min(pointer.x + 14, maxLeft),
      top: Math.min(pointer.y + 14, maxTop),
    }
  }, [pointer.x, pointer.y])

  if (disabled || (details.length === 0 && !note)) {
    return <div className={className}>{children}</div>
  }

  return (
    <>
      <div
        className={className}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onMouseMove={(event) => setPointer({ x: event.clientX, y: event.clientY })}
      >
        {children}
      </div>
      {hovered && typeof window !== "undefined"
        ? createPortal(
            <div
              className={cn(
                "pointer-events-none fixed z-[9999] hidden min-w-64 max-w-[22rem] rounded-xl border border-border/80 bg-background/95 p-3 shadow-xl backdrop-blur md:block",
                panelClassName
              )}
              style={popupStyle}
            >
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</p>
              {details.length > 0 ? (
                <div className="mt-2 space-y-1.5">
                  {details.map((row) => (
                    <div key={`${title}-${row.label}-${row.value}`} className="flex items-start justify-between gap-3 text-xs">
                      <span className="text-muted-foreground">{row.label}</span>
                      <span className="text-right font-semibold text-foreground">{row.value}</span>
                    </div>
                  ))}
                </div>
              ) : null}
              {note ? (
                <div className={cn("border-border/60 pt-2", details.length > 0 ? "mt-2 border-t" : "mt-1")}>
                  <p className="text-[11px] leading-relaxed text-muted-foreground">{note}</p>
                </div>
              ) : null}
            </div>,
            document.body
          )
        : null}
    </>
  )
}
