"use client";

import { cn } from "cn";
import { Info } from "lucide-react";
import { useSyncExternalStore, type ReactNode } from "react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const COARSE = "(pointer: coarse)";

function subscribe(onChange: () => void) {
  const query = window.matchMedia(COARSE);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

/** True on touch-first devices, where hover does not exist. False during SSR. */
export function useCoarsePointer(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(COARSE).matches,
    () => false,
  );
}

/**
 * Explanation attached to a term or an ⓘ icon.
 *
 * Radix tooltips open on hover/focus only, so on phones they never appeared. Here a
 * touch device gets a popover (tap to open, tap outside to close); mouse users keep the
 * hover tooltip. Without `children`, an accessible ⓘ button is rendered.
 */
export function Hint({
  content,
  children,
  label,
  className,
}: {
  content: ReactNode;
  /** The term being explained; omitted → ⓘ icon. */
  children?: ReactNode;
  /** Accessible name of the ⓘ icon button. */
  label?: string;
  className?: string;
}) {
  const coarse = useCoarsePointer();
  const trigger = children ?? <Info className="size-3.5" aria-hidden />;
  const triggerClass = cn(
    children
      ? "text-left underline decoration-dotted underline-offset-2"
      : "-m-2 inline-flex p-2 text-subtle-foreground hover:text-foreground",
    "rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
    className,
  );
  const aria = children ? undefined : `Sobre: ${label ?? "este item"}`;

  if (coarse) {
    return (
      <Popover>
        <PopoverTrigger type="button" aria-label={aria} className={triggerClass}>
          {trigger}
        </PopoverTrigger>
        <PopoverContent side="top" className="w-72 text-sm leading-relaxed text-muted-foreground">
          {content}
        </PopoverContent>
      </Popover>
    );
  }
  return (
    <Tooltip>
      <TooltipTrigger type="button" aria-label={aria} className={triggerClass}>
        {trigger}
      </TooltipTrigger>
      <TooltipContent className="max-w-72">{content}</TooltipContent>
    </Tooltip>
  );
}
