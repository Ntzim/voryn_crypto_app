"use client";

import { cn } from "cn";
import { ShieldAlert, Target, TriangleAlert } from "lucide-react";
import { Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, YAxis } from "recharts";

import { AssetIcon } from "@/components/common/asset-icon";
import { Skeleton } from "@/components/ui/skeleton";
import type { Locale, Signal, SignalClass, SignalHistoryPoint } from "@/lib/api/types";
import { formatDateTime, formatNumber, formatPercent, formatPrice } from "@/lib/format";
import { SIGNAL_META } from "@/lib/signal-queries";

export function ClassificationBadge({ value, className }: { value: SignalClass; className?: string }) {
  return (
    <span className={cn("inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap", SIGNAL_META[value].tone, className)}>
      {SIGNAL_META[value].label}
    </span>
  );
}

/** Semicircular gauge; the arc is the score, not a probability. */
export function ScoreGauge({ score, classification, size = 88 }: { score: string; classification: SignalClass; size?: number }) {
  const value = Math.max(0, Math.min(100, Number(score)));
  const r = 40;
  const circumference = Math.PI * r;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size * 0.62 }} role="img" aria-label={`Score ${formatNumber(score, "pt-BR", { digits: 0 })} de 100`}>
      <svg viewBox="0 0 100 60" className="h-full w-full">
        <path d="M10 52 A40 40 0 0 1 90 52" fill="none" stroke="rgb(148 163 184 / 0.15)" strokeWidth="8" strokeLinecap="round" />
        <path
          d="M10 52 A40 40 0 0 1 90 52"
          fill="none"
          stroke={SIGNAL_META[classification].color}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={`${(value / 100) * circumference} ${circumference}`}
        />
      </svg>
      <span className="num absolute inset-x-0 bottom-0 text-center font-heading text-xl font-semibold text-foreground">
        {formatNumber(score, "pt-BR", { digits: 0 })}
      </span>
    </div>
  );
}

export function SignalSummaryRow({ signal, locale }: { signal: Signal; locale: Locale }) {
  return (
    <div className="flex items-center gap-3">
      <AssetIcon src={signal.asset.image_url} symbol={signal.asset.symbol} size={32} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-foreground">{signal.asset.name}</p>
        <p className="num text-xs text-muted-foreground">
          {signal.asset.symbol} · {formatPrice(signal.current_price ?? signal.reference_price, "USD", locale)}
        </p>
      </div>
      <ScoreGauge score={signal.score} classification={signal.classification} size={64} />
    </div>
  );
}

export function ComponentBars({ signal, locale }: { signal: Signal; locale: Locale }) {
  return (
    <ul className="space-y-3">
      {signal.components.map((c) => {
        const score = Number(c.score);
        const color = score >= 60 ? "bg-success" : score <= 40 ? "bg-destructive" : "bg-muted-foreground";
        return (
          <li key={c.key}>
            <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
              <span className="font-medium text-foreground">
                {c.label} <span className="text-xs font-normal text-subtle-foreground">· peso {formatNumber(c.weight_pct, locale, { digits: 0 })}%</span>
              </span>
              <span className="num text-xs text-muted-foreground">{formatNumber(c.score, locale, { digits: 0 })}/100</span>
            </div>
            <div className="relative h-1.5 rounded-full bg-accent">
              <span className="absolute top-1/2 left-1/2 h-2.5 w-px -translate-y-1/2 bg-border-strong" aria-hidden />
              <div className={cn("h-full rounded-full", color)} style={{ width: `${score}%` }} />
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{c.detail}</p>
          </li>
        );
      })}
    </ul>
  );
}

export function RisksAndInvalidation({ signal }: { signal: Signal }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div>
        <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-warning">
          <ShieldAlert className="size-3.5" /> Riscos
        </p>
        {signal.risks.length ? (
          <ul className="space-y-1.5 text-sm text-muted-foreground">
            {signal.risks.map((r) => (
              <li key={r}>• {r}</li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">Nenhum risco específico identificado pelas regras — o risco de mercado permanece.</p>
        )}
      </div>
      <div>
        <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-primary-ink">
          <Target className="size-3.5" /> Condições de invalidação
        </p>
        <ul className="space-y-1.5 text-sm text-muted-foreground">
          {signal.invalidation.map((r) => (
            <li key={r}>• {r}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

const QUALITY_TITLE: Record<Signal["data_quality"], string> = {
  valid: "",
  stale: "Dados desatualizados",
  incomplete: "Dados insuficientes",
  anomalous: "Dados inconsistentes",
  unavailable: "Fonte de dados indisponível",
};

/** Data-quality warning; renders nothing for a current signal built on valid data. */
export function DataQualityNotice({ signal }: { signal: Signal }) {
  if (signal.is_current && signal.data_quality === "valid") return null;
  return (
    <div role="status" className="rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs text-warning">
      <p className="flex items-center gap-1.5 font-medium">
        <TriangleAlert className="size-3.5" />
        {QUALITY_TITLE[signal.data_quality] || "Análise histórica"}
        {signal.is_current ? " — compra e venda suspensas" : " — análise histórica, não é uma recomendação atual"}
      </p>
      {signal.quality_reasons.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 text-warning/90">
          {signal.quality_reasons.map((r) => (
            <li key={r}>• {r}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function SignalProvenance({ signal, locale, timeZone }: { signal: Signal; locale: Locale; timeZone: string }) {
  const change =
    signal.current_price && Number(signal.reference_price) > 0
      ? (Number(signal.current_price) / Number(signal.reference_price) - 1) * 100
      : null;
  return (
    <div className="space-y-2 text-xs text-subtle-foreground">
      <p>
        Candle {signal.timeframe} de {formatDateTime(signal.candle_time, locale, timeZone)} · preço de referência{" "}
        {formatPrice(signal.reference_price, "USD", locale)}
        {change !== null && <> ({formatPercent(change, locale)} desde então)</>} · fonte {signal.data_source.replace(":", " ")} · estratégia{" "}
        {signal.strategy_key} v{signal.strategy_version} · metodologia {signal.methodology_version} · qualidade dos dados{" "}
        {signal.data_quality === "valid" ? "válida" : QUALITY_TITLE[signal.data_quality].toLowerCase()}
      </p>
    </div>
  );
}

export function ScoreHistory({ points, loading, locale }: { points: SignalHistoryPoint[] | undefined; loading: boolean; locale: Locale }) {
  if (loading || !points) return <Skeleton className="h-28 w-full rounded-lg" />;
  if (points.length < 2) {
    return <p className="text-sm text-muted-foreground">O histórico de score aparece a partir do segundo candle analisado.</p>;
  }
  const data = points.map((p) => ({ t: p.candle_time, score: Number(p.score) }));
  return (
    <div className="h-28 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 6, right: 4, bottom: 0, left: -24 }}>
          <YAxis domain={[0, 100]} ticks={[35, 65]} tick={{ fill: "#64748B", fontSize: 10 }} axisLine={false} tickLine={false} />
          <ReferenceLine y={65} stroke="rgba(34,197,94,0.35)" strokeDasharray="3 3" />
          <ReferenceLine y={35} stroke="rgba(239,68,68,0.35)" strokeDasharray="3 3" />
          <Tooltip
            contentStyle={{ background: "#151D28", border: "1px solid rgba(148,163,184,.2)", borderRadius: 8, fontSize: 12 }}
            labelFormatter={(t) => formatDateTime(String(t), locale)}
            formatter={(v) => [formatNumber(Number(v), locale, { digits: 0 }), "Score"]}
          />
          <Line type="monotone" dataKey="score" stroke="#6366F1" strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
