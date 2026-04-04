/**
 * InsightPopup — modal popup for displaying full AI insight details.
 *
 * Built on shadcn Dialog so focus trapping, backdrop, and Escape key
 * handling are provided by Radix Dialog — not reimplemented here.
 *
 * Desktop: centered modal with backdrop (Dialog default behavior).
 * Mobile (<640px): bottom sheet sliding up from screen bottom via
 * className overrides on DialogContent.
 *
 * Backdrop click closes (Radix Dialog default). Body click does NOT close
 * because stopPropagation is implicit in Dialog.Content boundaries.
 *
 * Focus returns to the trigger element on close (Radix Dialog behavior).
 * Tab cycles within Dialog.Content automatically.
 *
 * @param isOpen - Controls visibility
 * @param onClose - Called when user dismisses the popup
 * @param title - Header title text
 * @param subtitle - Optional muted subtitle below title
 * @param children - Popup body content
 * @param actions - Optional footer action button configs
 * @param size - "sm" (480px) | "md" (600px) | "lg" (760px). Default "md".
 */
"use client";

import React from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

export interface InsightPopupAction {
  label: string;
  onClick: () => void;
  variant?: "default" | "outline" | "ghost" | "destructive";
}

interface InsightPopupProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  actions?: InsightPopupAction[];
  size?: "sm" | "md" | "lg";
}

const SIZE_CLASSES: Record<string, string> = {
  sm: "sm:max-w-[480px]",
  md: "sm:max-w-[600px]",
  lg: "sm:max-w-[760px]",
};

export function InsightPopup({
  isOpen,
  onClose,
  title,
  subtitle,
  children,
  actions,
  size = "md",
}: InsightPopupProps) {
  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent
        className={`
          ${SIZE_CLASSES[size]}
          animate-popup-in motion-reduce:animate-none
          sm:rounded-[var(--radius)]
          max-sm:fixed max-sm:bottom-0 max-sm:left-0 max-sm:right-0
          max-sm:top-auto max-sm:translate-x-0 max-sm:translate-y-0
          max-sm:rounded-t-2xl max-sm:rounded-b-none
          max-sm:animate-sheet-in
          p-0
        `}
      >
        {/* Header */}
        <DialogHeader className="px-6 pt-5 pb-4 border-b border-gray-100">
          <DialogTitle className="text-[15px] font-semibold leading-snug">
            {title}
          </DialogTitle>
          {subtitle && (
            <DialogDescription className="text-[13px] text-gray-500 mt-0.5">
              {subtitle}
            </DialogDescription>
          )}
        </DialogHeader>

        {/* Body */}
        <div className="px-6 py-5 max-h-[60vh] overflow-y-auto popup-scroll">
          {children}
        </div>

        {/* Footer */}
        {actions && actions.length > 0 && (
          <DialogFooter className="px-6 py-4 border-t border-gray-100 flex justify-end gap-2">
            {actions.map((action, i) => (
              <Button
                key={i}
                variant={action.variant ?? "outline"}
                size="sm"
                onClick={action.onClick}
                className="transition-all duration-150 ease-in-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2"
              >
                {action.label}
              </Button>
            ))}
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}
