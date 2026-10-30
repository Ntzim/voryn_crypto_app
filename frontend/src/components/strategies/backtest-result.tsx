"use client";

import { cn } from "cn";
import { ColorType, createChart, LineSeries, LineStyle, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";

import { AssetIcon } from "@/components/common/asset-icon";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Backtest, BacktestMetrics, BacktestResult, BacktestStrategy, Locale } from "@/lib/api/types";
import { formatDateTime, formatNumber, formatPercent, formatPrice } from "@/lib/format";
import { usePreferences } from "@/lib/queries";

const COLORS = {
  strategy: "#6366F1",
  benchmark: "#94A3B8",
  grid: "rgba(148, 163, 184, 0.08)",
  text: "#94A3B8",
};

const PARAM_LABEL: Record<string, string> = {
  fast: "rápida",
  slow: "lenta",
  signal: "sinal",
  low: "compra <",
  high: "venda >",
  period: "período",
  strategy: "estratégia",
  version: "versão",
};

function paramsText(params: Record<string, string | number>): string {
  if (params.strategy) return `${params.strategy} v${params.version}`;
  const entries = Object.entries(params);
  return entries.length ? entries.map(([k, v]) => `${PARAM_LABEL[k] ?? k} ${v}`).join(" · ") : "padrão";
}

export function BacktestResultView({ run, strategies }: { run: Backtest; strategies: BacktestStrategy[] | undefined }) {
  const { locale, timeZone } = usePreferences();
  const result = run.result;
  if (!result) return null;
  const label = strategies?.find((s) => s.key === run.strategy)?.label ?? run.strategy;
  const date = (iso: string | null | undefined) => formatDateTime(iso, locale, timeZone, { dateStyle: "short" });
  const validation = result.validation;
  const beat = Number(validation.strategy.total_return_pct) > Number(validation.benchmark.total_return_pct);

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardContent className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <AssetIcon src={run.asset.image_url} symbol={run.asset.symbol} size={36} />
            <div>
              <p className="font-heading text-lg font-semibold text-foreground">
                {run.asset.symbol} · {label}
              </p>
              <p className="text-xs text-muted-foreground">
                {run.timeframe === "1d" ? "Diário" : "4 horas"} · {result.candles} candles ({date(result.first_candle)} a {date(result.last_candle)}) ·
                parâmetros: {paramsText(result.selected_params)} · taxa {formatNumber(Number(run.fee_bps) / 100, locale)}% · slippage{" "}
                {formatNumber(Number(run.slippage_bps) / 100, locale)}%
              </p>
            </div>
          </div>
          <div className="num text-right">
            <p className="text-xs text-muted-foreground">Validação (fora da amostra)</p>
            <p className={cn("font-heading text-2xl font-semibold", Number(validation.strategy.total_return_pct) >= 0 ? "text-success" : "text-destructive")}>
              {formatPercent(validation.strategy.total_return_pct, locale, 1)}
            </p>
            <p className="text-xs text-muted-foreground">
              Comprar e manter: {formatPercent(validation.benchmark.total_return_pct, locale, 1)} ·{" "}
              <span className={beat ? "text-success" : "text-warning"}>{beat ? "superou" : "não superou"}</span>
            </p>
          </div>
        </CardContent>
      </Card>

      <EquityCard result={result} locale={locale} />
      <MetricsTable result={result} locale={locale} date={date} />

      <div className="grid gap-4 lg:grid-cols-2">
        {result.grid.length > 0 && <GridCard result={result} locale={locale} />}
        <TradesCard result={result} locale={locale} date={date} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="font-heading text-sm font-medium">Como este resultado foi calculado</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted-foreground">
            {result.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
            <li>
              Dados: {result.data_source} ({result.quote}) · obtidos em {formatDateTime(result.data_fetched_at, locale, timeZone)} · motor {run.engine_version}
            </li>
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

function EquityCard({ result, locale }: { result: BacktestResult; locale: Locale }) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = container.current;
    if (!el || result.equity.length < 2) return;
    const chart = createChart(el, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: COLORS.text, fontFamily: "var(--font-inter)", attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { color: COLORS.grid } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, fixLeftEdge: true, fixRightEdge: true },
      localization: { locale, priceFormatter: (v: number) => v.toLocaleString(locale, { maximumFractionDigits: 0 }) },
      handleScroll: false,
      handleScale: false,
    });
    const time = (iso: string) => (Date.parse(iso) / 1000) as UTCTimestamp;
    // Each segment starts from the same capital, so it is drawn as its own pair of lines.
    for (const segment of ["train", "validation"] as const) {
      const points = result.equity.filter((p) => p.segment === segment);
      const dashed = segment === "train";
      const strategy = chart.addSeries(LineSeries, { color: COLORS.strategy, lineWidth: 2, lineStyle: dashed ? LineStyle.Dashed : LineStyle.Solid, priceLineVisible: false, lastValueVisible: !dashed });
      strategy.setData(points.map((p) => ({ time: time(p.time), value: Number(p.strategy) })));
      const bench = chart.addSeries(LineSeries, { color: COLORS.benchmark, lineWidth: 1, lineStyle: dashed ? LineStyle.Dashed : LineStyle.Solid, priceLineVisible: false, lastValueVisible: !dashed });
      bench.setData(points.map((p) => ({ time: time(p.time), value: Number(p.benchmark) })));
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [result, locale]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-heading text-sm font-medium">Evolução de {formatNumber(result.initial_capital, locale, { digits: 0 })} {result.quote} em cada período</CardTitle>
      </CardHeader>
      <CardContent>
        <div ref={container} className="h-64 w-full md:h-72" />
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <Legend color={COLORS.strategy} label="Estratégia" />
          <Legend color={COLORS.benchmark} label="Comprar e manter" />
          <span>Tracejado: treino · contínuo: validação (recomeça do capital inicial)</span>
        </div>
      </CardContent>
    </Card>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-0.5 w-4 rounded" style={{ backgroundColor: color }} />
      {label}
    </span>
  );
}

const ROWS: { key: keyof BacktestMetrics; label: string; kind: "pct" | "signed" | "num" | "int" }[] = [
  { key: "total_return_pct", label: "Retorno total", kind: "signed" },
  { key: "cagr_pct", label: "Retorno anualizado", kind: "signed" },
  { key: "max_drawdown_pct", label: "Drawdown máximo", kind: "signed" },
  { key: "volatility_pct", label: "Volatilidade anualizada", kind: "pct" },
  { key: "sharpe", label: "Sharpe (sem taxa livre de risco)", kind: "num" },
  { key: "trades", label: "Operações", kind: "int" },
  { key: "win_rate_pct", label: "Taxa de acerto", kind: "pct" },
  { key: "avg_trade_pct", label: "Resultado médio por operação", kind: "signed" },
  { key: "profit_factor", label: "Profit factor", kind: "num" },
  { key: "exposure_pct", label: "Tempo comprado", kind: "pct" },
  { key: "fees", label: "Taxas pagas (USDT)", kind: "num" },
];

function MetricsTable({ result, locale, date }: { result: BacktestResult; locale: Locale; date: (iso: string | null | undefined) => string }) {
  const fmt = (m: BacktestMetrics, row: (typeof ROWS)[number]) => {
    const v = m[row.key] as string | number | null;
    if (v === null) return "—";
    if (row.kind === "signed") return formatPercent(v, locale, 1);
    if (row.kind === "pct") return `${formatNumber(v, locale, { digits: 1 })}%`;
    if (row.kind === "int") return String(v);
    return formatNumber(v, locale);
  };
  const cols = [
    { m: result.train.strategy, head: "Estratégia" },
    { m: result.train.benchmark, head: "Comprar e manter" },
    { m: result.validation.strategy, head: "Estratégia" },
    { m: result.validation.benchmark, head: "Comprar e manter" },
  ];
  return (
    <Card className="gap-0 py-0">
      <div className="overflow-x-auto">
        <table className="num w-full min-w-[640px] text-sm">
          <thead className="text-xs text-muted-foreground">
            <tr className="border-b border-border">
              <th className="px-5 pt-4 pb-1 text-left font-medium" />
              <th colSpan={2} className="px-3 pt-4 pb-1 text-center font-medium text-foreground">
                Treino <span className="font-normal text-muted-foreground">({date(result.train.strategy.start)} a {date(result.train.strategy.end)})</span>
              </th>
              <th colSpan={2} className="px-3 pt-4 pb-1 text-center font-medium text-foreground">
                Validação <span className="font-normal text-muted-foreground">({date(result.validation.strategy.start)} a {date(result.validation.strategy.end)})</span>
              </th>
            </tr>
            <tr className="border-b border-border">
              <th className="px-5 py-2 text-left font-medium">Métrica</th>
              {cols.map((c, i) => (
                <th key={i} className="px-3 py-2 text-right font-medium">
                  {c.head}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map((row) => (
              <tr key={row.key} className="border-b border-border last:border-0">
                <td className="px-5 py-2.5 text-muted-foreground">{row.label}</td>
                {cols.map((c, i) => (
                  <td key={i} className={cn("px-3 py-2.5 text-right", i % 2 === 0 ? "text-foreground" : "text-muted-foreground")}>
                    {fmt(c.m, row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function GridCard({ result, locale }: { result: BacktestResult; locale: Locale }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-heading text-sm font-medium">Otimização no treino</CardTitle>
      </CardHeader>
      <CardContent>
        <table className="num w-full text-sm">
          <thead className="text-xs text-muted-foreground">
            <tr className="border-b border-border">
              <th className="py-2 text-left font-medium">Parâmetros</th>
              <th className="py-2 text-right font-medium">Sharpe</th>
              <th className="py-2 text-right font-medium">Retorno</th>
            </tr>
          </thead>
          <tbody>
            {result.grid.map((g) => (
              <tr key={JSON.stringify(g.params)} className={cn("border-b border-border last:border-0", g.selected && "text-primary-ink")}>
                <td className="py-2">
                  {paramsText(g.params)}
                  {g.selected && <span className="ml-2 text-xs">escolhido</span>}
                </td>
                <td className="py-2 text-right">{g.train_sharpe === null ? "—" : formatNumber(g.train_sharpe, locale)}</td>
                <td className="py-2 text-right">{formatPercent(g.train_return_pct, locale, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-3 text-[11px] text-subtle-foreground">Escolha pelo maior Sharpe no treino. Uma grande queda na validação indica sobreajuste.</p>
      </CardContent>
    </Card>
  );
}

function TradesCard({ result, locale, date }: { result: BacktestResult; locale: Locale; date: (iso: string | null | undefined) => string }) {
  const trades = [...result.trades].reverse().slice(0, 40);
  return (
    <Card className={cn(result.grid.length === 0 && "lg:col-span-2")}>
      <CardHeader>
        <CardTitle className="font-heading text-sm font-medium">Operações ({result.trades.length})</CardTitle>
      </CardHeader>
      <CardContent>
        {trades.length === 0 ? (
          <p className="text-sm text-muted-foreground">A estratégia não operou no período.</p>
        ) : (
          <div className="max-h-80 overflow-y-auto">
            <table className="num w-full text-sm">
              <thead className="sticky top-0 bg-card text-xs text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="py-2 text-left font-medium">Entrada</th>
                  <th className="py-2 text-left font-medium">Saída</th>
                  <th className="py-2 text-right font-medium">Resultado</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => (
                  <tr key={`${t.entry_time}-${t.segment}`} className="border-b border-border last:border-0">
                    <td className="py-2">
                      {date(t.entry_time)}
                      <span className="block text-xs text-muted-foreground">
                        {formatPrice(t.entry_price, "USD", locale)} · {t.segment === "train" ? "treino" : "validação"}
                      </span>
                    </td>
                    <td className="py-2">
                      {t.exit_time ? date(t.exit_time) : "em aberto"}
                      {t.exit_price && <span className="block text-xs text-muted-foreground">{formatPrice(t.exit_price, "USD", locale)}</span>}
                    </td>
                    <td className={cn("py-2 text-right", t.return_pct === null ? "text-muted-foreground" : Number(t.return_pct) >= 0 ? "text-success" : "text-destructive")}>
                      {t.return_pct === null ? "—" : formatPercent(t.return_pct, locale, 1)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-3 text-[11px] text-subtle-foreground">Preços de execução já incluem o slippage; o resultado desconta as taxas de entrada e saída.</p>
      </CardContent>
    </Card>
  );
}
