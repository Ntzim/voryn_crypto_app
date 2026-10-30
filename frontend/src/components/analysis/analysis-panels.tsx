"use client";

import { Hint } from "@/components/common/hint";
import { cn } from "cn";
import { ArrowDownRight, ArrowUpRight, Minus, TrendingDown, TrendingUp, Waves, HelpCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Analysis, Level, Locale, Trend } from "@/lib/api/types";
import { formatDateTime, formatNumber, formatPercent, formatPrice } from "@/lib/format";

export const TREND_META: Record<Trend["classification"], { label: string; icon: typeof TrendingUp; className: string }> = {
  uptrend: { label: "Tendência de alta", icon: TrendingUp, className: "text-success bg-success/10 border-success/30" },
  downtrend: { label: "Tendência de baixa", icon: TrendingDown, className: "text-destructive bg-destructive/10 border-destructive/30" },
  consolidation: { label: "Consolidação", icon: Waves, className: "text-warning bg-warning/10 border-warning/30" },
  undefined: { label: "Tendência indefinida", icon: HelpCircle, className: "text-muted-foreground bg-muted border-border-strong" },
};

const CONFIDENCE = { high: "alta", moderate: "moderada", low: "baixa" } as const;

export function TrendBadge({ trend, className }: { trend: Trend; className?: string }) {
  const meta = TREND_META[trend.classification];
  const Icon = meta.icon;
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium", meta.className, className)}>
      <Icon className="size-3.5" aria-hidden />
      {meta.label}
    </span>
  );
}

const VOTE = {
  bullish: { icon: ArrowUpRight, className: "text-success", label: "alta" },
  bearish: { icon: ArrowDownRight, className: "text-destructive", label: "baixa" },
  neutral: { icon: Minus, className: "text-muted-foreground", label: "neutro" },
} as const;

export function TrendCard({ trend }: { trend: Trend }) {
  return (
    <Card>
      <CardHeader className="flex flex-wrap items-center justify-between gap-2">
        <CardTitle className="font-heading text-sm font-medium">Tendência</CardTitle>
        <TrendBadge trend={trend} />
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-foreground">{trend.summary}</p>
        <p className="text-xs text-muted-foreground">
          Confiança {CONFIDENCE[trend.confidence]} · saldo {trend.score > 0 ? `+${trend.score}` : trend.score} de {trend.available} critérios
        </p>
        <ul className="space-y-2">
          {trend.criteria.map((c) => {
            const vote = VOTE[c.vote];
            const Icon = vote.icon;
            return (
              <li key={c.name} className="flex gap-2.5 text-sm">
                <Icon className={cn("mt-0.5 size-4 shrink-0", vote.className)} aria-label={vote.label} />
                <div>
                  <span className="font-medium text-foreground">{c.name}</span>
                  <span className="text-muted-foreground"> — {c.detail}</span>
                </div>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}

function Row({ label, value, hint, tone }: { label: string; value: React.ReactNode; hint: string; tone?: string }) {
  return (
    <div className="flex items-start justify-between gap-3 py-2.5">
      <Hint className="text-sm text-muted-foreground" content={<>{hint}</>}>
        {label}
      </Hint>
      <span className={cn("num text-right text-sm font-medium text-foreground", tone)}>{value}</span>
    </div>
  );
}

export function IndicatorsCard({ analysis, locale, timeZone }: { analysis: Analysis; locale: Locale; timeZone: string }) {
  const s = analysis.snapshot;
  if (!s) return null;
  const price = (v: string | null) => formatPrice(v, "USD", locale);
  const rsiLabel = s.rsi_state === "overbought" ? "sobrecompra" : s.rsi_state === "oversold" ? "sobrevenda" : "neutro";
  const vsClose = (v: string | null) => {
    if (v === null) return "—";
    const above = Number(s.close) > Number(v);
    return (
      <span className="inline-flex flex-col items-end">
        {price(v)}
        <span className={cn("text-xs font-normal", above ? "text-success" : "text-destructive")}>preço {above ? "acima" : "abaixo"}</span>
      </span>
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-heading text-sm font-medium">Indicadores</CardTitle>
        <p className="text-xs text-muted-foreground">
          Último candle fechado: {formatDateTime(s.as_of, locale, timeZone)}
        </p>
      </CardHeader>
      <CardContent className="divide-y divide-border">
        <Row
          label="RSI (14)"
          hint="Índice de força relativa de Wilder. Acima de 70 indica sobrecompra; abaixo de 30, sobrevenda. Não é sinal de reversão por si só."
          value={<>{formatNumber(s.rsi, locale, { digits: 1 })} <span className="text-xs font-normal text-muted-foreground">({rsiLabel})</span></>}
          tone={s.rsi_state === "overbought" ? "text-destructive" : s.rsi_state === "oversold" ? "text-success" : undefined}
        />
        <Row
          label="MACD (12, 26, 9)"
          hint="Diferença entre as médias exponenciais de 12 e 26 períodos, comparada à sua média de 9. Cruzamentos indicam mudança de momentum."
          value={
            <span className="inline-flex flex-col items-end">
              {formatNumber(s.macd_hist, locale, { digits: 4 })}
              <span className="text-xs font-normal text-muted-foreground">
                {s.macd_cross
                  ? `cruzamento ${s.macd_cross === "bullish" ? "positivo" : "negativo"} ${s.macd_cross_bars_ago === 0 ? "no último candle" : `há ${s.macd_cross_bars_ago} candle(s)`}`
                  : Number(s.macd_hist) >= 0 ? "histograma positivo" : "histograma negativo"}
              </span>
            </span>
          }
        />
        <Row label="EMA 21" hint="Média móvel exponencial de 21 períodos (curto prazo)." value={vsClose(s.ema21)} />
        <Row label="EMA 50" hint="Média móvel exponencial de 50 períodos (médio prazo)." value={vsClose(s.ema50)} />
        <Row label="EMA 200" hint="Média móvel exponencial de 200 períodos (longo prazo). Requer ao menos 200 candles." value={vsClose(s.ema200)} />
        <Row
          label="Bandas de Bollinger (20, 2)"
          hint="Média de 20 períodos ± 2 desvios-padrão. %B mostra onde o preço está entre as bandas (0 = inferior, 1 = superior); a largura mede a volatilidade."
          value={
            <span className="inline-flex flex-col items-end">
              %B {formatNumber(s.bb_percent_b, locale, { digits: 2 })}
              <span className="text-xs font-normal text-muted-foreground">largura {formatNumber(s.bb_bandwidth_pct, locale, { digits: 1 })}%</span>
            </span>
          }
        />
        <Row
          label="ATR (14)"
          hint="Amplitude média verdadeira de Wilder: quanto o preço costuma se mover por candle. Útil para dimensionar stops e avaliar risco."
          value={<span className="inline-flex flex-col items-end">{price(s.atr)}<span className="text-xs font-normal text-muted-foreground">{formatNumber(s.atr_pct, locale, { digits: 2 })}% do preço</span></span>}
        />
        <Row
          label="Volume"
          hint="Volume do último candle fechado comparado à média de 20 candles. Acima de 1,5× é considerado relevante."
          value={s.volume_ratio ? `${formatNumber(s.volume_ratio, locale, { digits: 2 })}× a média` : "—"}
          tone={Number(s.volume_ratio) >= 1.5 ? "text-primary-ink" : undefined}
        />
        <Row
          label="Volatilidade anualizada"
          hint="Desvio-padrão dos retornos logarítmicos dos últimos 30 candles, anualizado (mercado 24/7)."
          value={s.volatility_annualized_pct ? `${formatNumber(s.volatility_annualized_pct, locale, { digits: 1 })}%` : "—"}
        />
      </CardContent>
    </Card>
  );
}

function LevelList({ levels, kind, locale }: { levels: Level[]; kind: "support" | "resistance"; locale: Locale }) {
  if (!levels.length) {
    return <p className="py-2 text-sm text-muted-foreground">Nenhum nível identificado no período.</p>;
  }
  return (
    <ul className="divide-y divide-border">
      {levels.map((l) => (
        <li key={l.price} className="num flex items-center justify-between py-2 text-sm">
          <span className="font-medium text-foreground">{formatPrice(l.price, "USD", locale)}</span>
          <span className="text-xs whitespace-nowrap text-muted-foreground">
            {l.touches}× ·{" "}
            <span className={kind === "support" ? "text-success" : "text-destructive"}>{formatPercent(l.distance_pct, locale)}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

export function LevelsCard({ analysis, locale }: { analysis: Analysis; locale: Locale }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-heading text-sm font-medium">Suportes e resistências</CardTitle>
        <Hint className="w-fit text-xs text-muted-foreground" content={<>Topos e fundos locais (máxima/mínima estrita entre 3 candles de cada lado) agrupados quando distam menos de
            0,5 × ATR. A força é o número de toques. Níveis não garantem reação do preço.</>}>
          Como são calculados
        </Hint>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1">
        <div>
          <p className="mb-1 text-xs font-medium text-destructive">Resistências</p>
          <LevelList levels={analysis.resistances} kind="resistance" locale={locale} />
        </div>
        <div>
          <p className="mb-1 text-xs font-medium text-success">Suportes</p>
          <LevelList levels={analysis.supports} kind="support" locale={locale} />
        </div>
      </CardContent>
    </Card>
  );
}

export function SourceNote({ analysis, locale }: { analysis: Analysis; locale: Locale }) {
  return (
    <p className="text-xs text-subtle-foreground">
      Candles: Binance {analysis.pair.replace("USDT", "/USDT")} (USDT como referência de dólar) · atualizado{" "}
      {formatDateTime(analysis.fetched_at, locale, undefined, { timeStyle: "short" })} · metodologia {analysis.methodology_version}. Indicadores
      calculados apenas com candles fechados. Análise informativa, não é recomendação de investimento.
      {analysis.is_stale && <Badge variant="outline" className="ml-2 border-warning/40 text-warning">dados desatualizados</Badge>}
    </p>
  );
}
