"use client";

import { cn } from "cn";

import type { Currency } from "@/lib/api/types";

const OPTIONS: Currency[] = ["BRL", "USD"];

export function CurrencyToggle({ value, onChange }: { value: Currency; onChange: (c: Currency) => void }) {
  return (
    <div role="radiogroup" aria-label="Moeda de exibição" className="inline-flex rounded-lg border border-border bg-surface p-0.5">
      {OPTIONS.map((option) => (
        <button
          key={option}
          type="button"
          role="radio"
          aria-checked={value === option}
          onClick={() => onChange(option)}
          className={cn(
            "h-8 rounded-md px-3 text-xs font-medium transition-colors",
            value === option ? "bg-card text-foreground shadow-sm ring-1 ring-border-strong" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {option}
        </button>
      ))}
    </div>
  );
}
