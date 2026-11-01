"use client";

import { cn } from "cn";
import { Moon, Sun } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { ResolvedTheme, ThemePreference } from "@/lib/theme";

type Props = {
  resolved: ResolvedTheme | undefined;
  onChange: (preference: ThemePreference) => void;
  className?: string;
};

/**
 * Light/dark switch: a small track whose thumb slides between a sun and a moon.
 * The 44×44 hit area (HIG) is larger than the 52×28 visual. Until the theme is known
 * (server render, hydration) it renders neutral, so the markup never mismatches.
 */
export function ThemeToggle({ resolved, onChange, className }: Props) {
  const dark = resolved === "dark";
  const label = dark ? "Usar tema claro" : "Usar tema escuro";
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          role="switch"
          aria-checked={dark}
          aria-label="Alternar tema"
          disabled={resolved === undefined}
          onClick={() => onChange(dark ? "light" : "dark")}
          className={cn(
            "group relative inline-flex h-11 min-w-11 items-center justify-center rounded-full outline-offset-2 focus-visible:outline-2 focus-visible:outline-ring disabled:cursor-default",
            className,
          )}
          data-theme-toggle
        >
          <span
            className={cn(
              "relative flex h-7 w-[52px] items-center rounded-full bg-muted shadow-raised ring-1 ring-border transition-colors duration-300",
              "group-hover:ring-border-strong group-active:scale-95 transition-transform",
            )}
          >
            {/* Track icons: the inactive mode stays visible, faint, on its side. */}
            <Sun className="absolute left-[7px] size-3.5 text-subtle-foreground" aria-hidden strokeWidth={2} />
            <Moon className="absolute right-[7px] size-3.5 text-subtle-foreground" aria-hidden strokeWidth={2} />
            <span
              className={cn(
                "absolute top-[3px] left-[3px] flex size-[22px] items-center justify-center rounded-full bg-surface shadow-[0_1px_3px_rgb(0_0_0/0.2)] ring-1 ring-border",
                "transition-transform duration-300 ease-(--ease-out-soft)",
                dark && "translate-x-6",
                resolved === undefined && "opacity-0",
              )}
            >
              <Sun
                className={cn(
                  "absolute size-3.5 text-warning transition-[opacity,transform] duration-300 ease-(--ease-out-soft)",
                  dark ? "scale-50 -rotate-90 opacity-0" : "scale-100 rotate-0 opacity-100",
                )}
                aria-hidden
                strokeWidth={2.25}
              />
              <Moon
                className={cn(
                  "absolute size-3.5 text-primary-ink transition-[opacity,transform] duration-300 ease-(--ease-out-soft)",
                  dark ? "scale-100 rotate-0 opacity-100" : "scale-50 rotate-90 opacity-0",
                )}
                aria-hidden
                strokeWidth={2.25}
              />
            </span>
          </span>
        </button>
      </TooltipTrigger>
      <TooltipContent>{resolved ? label : "Alternar tema"}</TooltipContent>
    </Tooltip>
  );
}
