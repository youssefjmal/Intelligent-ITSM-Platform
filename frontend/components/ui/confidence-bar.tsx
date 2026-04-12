/**
 * ConfidenceBar — compact horizontal bar showing AI confidence level.
 *
 * Replaces raw percentage badges with a visual bar + label combination.
 * Color adapts to the confidence level (high=teal, medium=amber, low=red,
 * general_knowledge=blue). Used in chat bubbles, recommendation cards, and
 * the ticket detail panel.
 *
 * @param confidence - Float 0–1. Clamped internally if out of range.
 * @param band - "high" | "medium" | "low" | "general_knowledge"
 * @param showLabel - Whether to show the text label. Default true.
 * @param size - "sm" | "md" | "lg". Default "md".
 */
"use client";

import React from "react";

interface ConfidenceBarProps {
  confidence: number;
  band: "high" | "medium" | "low" | "general_knowledge";
  showLabel?: boolean;
  size?: "sm" | "md" | "lg";
}

const BAND_COLORS: Record<string, string> = {
  high: "#1D9E75",
  medium: "#EF9F27",
  low: "#E24B4A",
  general_knowledge: "#378ADD",
};

const BAND_LABELS: Record<string, { fr: string; en: string }> = {
  high: { fr: "Élevée", en: "High" },
  medium: { fr: "Moyenne", en: "Medium" },
  low: { fr: "Faible", en: "Low" },
  general_knowledge: { fr: "Connaissance générale", en: "General knowledge" },
};

const SIZE_TRACK: Record<string, string> = {
  sm: "h-[3px]",
  md: "h-[3px]",
  lg: "h-[4px]",
};

const SIZE_TEXT: Record<string, string> = {
  sm: "text-[11px]",
  md: "text-[12px]",
  lg: "text-[13px]",
};

export function ConfidenceBar({
  confidence,
  band,
  showLabel = true,
  size = "md",
}: ConfidenceBarProps) {
  const clamped = Math.max(0, Math.min(1, confidence));
  const color = BAND_COLORS[band] ?? "#888";
  const label = BAND_LABELS[band]?.fr ?? band;
  const percentage = Math.round(clamped * 100);

  return (
    <div className="flex flex-col gap-1 w-full min-w-[80px]">
      {showLabel && (
        <span className={`${SIZE_TEXT[size]} text-gray-500 leading-none`}>
          {band === "general_knowledge"
            ? label
            : `${label} ${percentage}%`}
        </span>
      )}
      <div className={`w-full rounded-sm bg-gray-200 dark:bg-gray-700 ${SIZE_TRACK[size]}`}>
        <div
          className={`${SIZE_TRACK[size]} rounded-sm transition-all duration-300`}
          style={{ width: `${clamped * 100}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}
