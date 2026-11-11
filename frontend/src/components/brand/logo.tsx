"use client";

import { cn } from "cn";
import { useId } from "react";

/**
 * Voryn mark: two converging strokes forming a "V" — signal meeting evidence. The left stroke
 * carries the brand gradient, the right one the brand violet at 85%. Colors come from the tokens.
 */
export function LogoMark({ className }: { className?: string }) {
  // Unique per instance: the sidebar renders two logos and one is hidden; a shared id would point
  // the gradient at the hidden one and the stroke would not paint.
  const gradient = `voryn-mark-${useId().replace(/:/g, "")}`;
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      className={cn("size-7 shrink-0", className)}
    >
      <defs>
        <linearGradient id={gradient} x1="6" y1="6" x2="16" y2="26" gradientUnits="userSpaceOnUse">
          <stop offset="0" style={{ stopColor: "var(--brand-gradient-from)" }} />
          <stop offset="1" style={{ stopColor: "var(--brand-gradient-to)" }} />
        </linearGradient>
      </defs>
      <path d="M6.5 6.5 15 25.5" stroke={`url(#${gradient})`} strokeWidth="3.4" strokeLinecap="round" />
      <path d="M25.5 6.5 17 25.5" style={{ stroke: "var(--brand)" }} strokeOpacity="0.85" strokeWidth="3.4" strokeLinecap="round" />
    </svg>
  );
}

export function Logo({ className, collapsed = false }: { className?: string; collapsed?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark />
      {!collapsed && (
        <span className="font-brand text-[15px] font-medium tracking-[0.32em] text-foreground">
          VORYN
        </span>
      )}
    </span>
  );
}
