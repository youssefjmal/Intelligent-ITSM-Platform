"use client"

type AssistantMascotProps = {
  locale?: string
  compact?: boolean
  speaking?: boolean
  className?: string
}

export function AssistantMascot({
  locale = "en",
  compact = false,
  speaking = false,
  className = "",
}: AssistantMascotProps) {
  const label = locale === "fr" ? "Assistant IA" : "AI assistant"

  return (
    <div
      aria-label={label}
      className={`assistant-mascot ${compact ? "assistant-mascot--compact" : ""} ${speaking ? "assistant-mascot--speaking" : ""} ${className}`.trim()}
    >
      <div className="assistant-mascot__halo" />
      <div className="assistant-mascot__body">
        <div className="assistant-mascot__antennas">
          <span />
          <span />
        </div>
        <div className="assistant-mascot__face">
          <span className="assistant-mascot__eye" />
          <span className="assistant-mascot__eye" />
          <span className="assistant-mascot__mouth" />
        </div>
      </div>
      <div className="assistant-mascot__spark assistant-mascot__spark--one" />
      <div className="assistant-mascot__spark assistant-mascot__spark--two" />
    </div>
  )
}
