import { cn } from "cn";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";

import type { Locale } from "@/lib/api/types";
import { formatPercent, trendOf } from "@/lib/format";

const TREND_CLASS = {
  up: "text-success",
  down: "text-destructive",
  flat: "text-muted-foreground",
} as const;

/** Percent change with color and direction (direction is also conveyed by sign for a11y). */
export function ChangeBadge({
  value,
  locale,
  variant = "text",
  className,
}: {
  value: string | null | undefined;
  locale?: Locale;
  variant?: "text" | "pill";
  className?: string;
}) {
  const trend = trendOf(value);
  const Icon = trend === "up" ? ArrowUpRight : trend === "down" ? ArrowDownRight : null;
  return (
    <span
      className={cn(
        "num inline-flex items-center gap-0.5 font-medium whitespace-nowrap",
        TREND_CLASS[trend],
        variant === "pill" && "rounded-md px-1.5 py-0.5 text-xs",
        variant === "pill" && trend === "up" && "bg-success/10",
        variant === "pill" && trend === "down" && "bg-destructive/10",
        variant === "pill" && trend === "flat" && "bg-muted",
        className,
      )}
    >
      {Icon && <Icon className="size-3.5" aria-hidden />}
      {formatPercent(value, locale)}
    </span>
  );
}
