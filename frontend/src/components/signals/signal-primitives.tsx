import { cn } from "cn";
import { ArrowDownRight, ArrowUpRight, Minus, TriangleAlert, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import type { Locale, SignalClass } from "@/lib/api/types";
import { formatNumber } from "@/lib/format";

/**
 * Signal and score are different things and look different: the signal (direction) uses its own
 * color plus a text label; the score (strength of the evidence) always uses the brand gradient.
 * Violet never stands for a signal.
 */
const SIGNAL_STYLE: Record<SignalClass, { label: string; className: string; dot: string }> = {
  buy_potential: { label: "Potencial de compra", className: "bg-signal-buy-soft text-signal-buy", dot: "bg-signal-buy" },
  attention: { label: "Atenção", className: "bg-signal-watch-soft text-signal-watch", dot: "bg-signal-watch" },
  neutral: { label: "Neutro", className: "bg-signal-neutral-soft text-signal-neutral", dot: "bg-signal-neutral-dot" },
  sell_potential: { label: "Potencial de venda", className: "bg-signal-sell-soft text-signal-sell", dot: "bg-signal-sell" },
};

/**
 * What each signal means in plain words. It describes the evidence; it never tells anyone to buy
 * or sell (the classification is analysis, not personalised advice).
 */
export const VERDICT: Record<SignalClass, { icon: LucideIcon; reading: string; border: string }> = {
  buy_potential: {
    icon: ArrowUpRight,
    reading: "Os indicadores estão alinhados a favor de alta. É o cenário mais favorável à compra entre os sinais.",
    border: "border-signal-buy/40",
  },
  sell_potential: {
    icon: ArrowDownRight,
    reading: "Os indicadores apontam enfraquecimento. Cenário desfavorável à compra e favorável a reduzir a posição.",
    border: "border-signal-sell/40",
  },
  attention: {
    icon: TriangleAlert,
    reading: "Sinais contraditórios ou risco elevado: não há leitura clara nem de compra nem de venda.",
    border: "border-signal-watch/40",
  },
  neutral: {
    icon: Minus,
    reading: "Evidência insuficiente para indicar compra ou venda. Vale acompanhar os próximos pregões.",
    border: "border-border",
  },
};

export function signalLabel(value: SignalClass): string {
  return SIGNAL_STYLE[value].label;
}

export function SignalDot({ value, className }: { value: SignalClass; className?: string }) {
  return <span aria-hidden className={cn("inline-block size-2 shrink-0 rounded-full", SIGNAL_STYLE[value].dot, className)} />;
}

/** Color is never the only cue: the badge carries a direction icon and its label. */
export function SignalBadge({ value, className }: { value: SignalClass; className?: string }) {
  const style = SIGNAL_STYLE[value];
  const Icon = VERDICT[value].icon;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-[6px] px-2 py-0.5 text-xs font-medium whitespace-nowrap", style.className, className)}>
      <Icon className="size-3.5 shrink-0" strokeWidth={2} aria-hidden />
      {style.label}
    </span>
  );
}

/** "4 de 6 critérios a favor · 1 contra": how much of the evidence points each way. */
export function EvidenceCount({ favorable, against, criteria, className }: { favorable: number; against: number; criteria: number; className?: string }) {
  if (!criteria) return null;
  return (
    <span className={cn("text-xs text-muted-foreground", className)}>
      <span className="num font-semibold text-signal-buy">{favorable}</span> de {criteria} critérios a favor
      {" · "}
      <span className="num font-semibold text-signal-sell">{against}</span> contra
    </span>
  );
}

/** The reading of one asset at a glance: direction, what it means and how much evidence. */
export function VerdictBanner({
  value,
  favorable,
  against,
  criteria,
  suspended,
}: {
  value: SignalClass;
  favorable: number;
  against: number;
  criteria: number;
  suspended?: string | null;
}) {
  const style = SIGNAL_STYLE[value];
  const verdict = VERDICT[value];
  const Icon = verdict.icon;
  return (
    <section aria-label="Leitura do sinal" className={cn("rounded-[12px] border p-4", style.className.split(" ")[0], verdict.border)}>
      <p className={cn("flex items-center gap-2 text-base font-semibold", style.className.split(" ")[1])}>
        <Icon className="size-5 shrink-0" strokeWidth={2} aria-hidden />
        {style.label}
      </p>
      <p className="mt-1.5 text-[13px] leading-5 text-foreground">{suspended ? `Compra e venda suspensas: ${suspended}` : verdict.reading}</p>
      {!suspended && <EvidenceCount favorable={favorable} against={against} criteria={criteria} className="mt-2 block" />}
    </section>
  );
}

/** Strength of the evidence, 0–100, filled with the brand gradient regardless of the signal. */
export function ScoreBar({ score, className }: { score: number; className?: string }) {
  const value = Math.max(0, Math.min(100, score));
  return (
    <span
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(value)}
      aria-label="Força da evidência"
      className={cn("relative inline-block h-1.5 w-16 overflow-hidden rounded-full bg-border", className)}
    >
      <span className="absolute inset-y-0 left-0 rounded-full bg-brand" style={{ width: `${value}%`, backgroundImage: "var(--gradient-brand)" }} />
    </span>
  );
}

export function ScoreValue({ score, locale = "pt-BR", size = "md" }: { score: number; locale?: Locale; size?: "md" | "lg" }) {
  return (
    <span className={cn("num font-bold text-foreground", size === "lg" ? "text-[26px] leading-none" : "text-sm")}>
      {formatNumber(score, locale, { digits: 0 })}
    </span>
  );
}

/** Trend balance as five squares: filled = criteria in favour (saldo), on a scale of `total`. */
export function TrendDots({ saldo, total, direction }: { saldo: number; total: number; direction: "alta" | "baixa" | "indefinida" }) {
  const filled = Math.max(0, Math.min(total, Math.abs(saldo)));
  const tone = direction === "alta" ? "bg-signal-buy" : direction === "baixa" ? "bg-signal-sell" : "bg-signal-neutral-dot";
  return (
    <span className="inline-flex gap-0.5" aria-hidden>
      {Array.from({ length: total }, (_, i) => (
        <span key={i} className={cn("size-2 rounded-[2px]", i < filled ? tone : "bg-surface-sunken")} />
      ))}
    </span>
  );
}

/** Filter chip: a real toggle button. Active state uses the brand, never a signal color. */
export function Chip({
  active,
  onClick,
  children,
  className,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-9 shrink-0 items-center gap-1.5 rounded-[10px] border px-3 text-xs font-medium whitespace-nowrap transition-colors",
        "pointer-coarse:h-10 pointer-coarse:rounded-full",
        active
          ? "border-brand bg-brand-soft text-brand-strong-text"
          : "border-border text-muted-foreground hover:border-input hover:text-foreground",
        className,
      )}
    >
      {children}
    </button>
  );
}
