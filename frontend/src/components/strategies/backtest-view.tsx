"use client";

import { cn } from "cn";
import { FlaskConical, Loader2, Play, Trash2 } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AssetIcon } from "@/components/common/asset-icon";
import { PageHeader } from "@/components/common/page-header";
import { EmptyState, ErrorState } from "@/components/common/states";
import { AssetPicker } from "@/components/portfolio/asset-picker";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { ApiError } from "@/lib/api/client";
import type { AssetBrief, BacktestInput, BacktestStrategy, BacktestSummary, Locale } from "@/lib/api/types";
import { useBacktest, useBacktestMutations, useBacktests, useBacktestStrategies } from "@/lib/backtest-queries";
import { formatDateTime, formatPercent, parseDecimalInput } from "@/lib/format";
import { usePreferences } from "@/lib/queries";

import { BacktestResultView } from "./backtest-result";

type StrategyKey = BacktestInput["strategy"];
type Timeframe = NonNullable<BacktestInput["timeframe"]>;

export const STATUS = {
  queued: { label: "Na fila", className: "text-muted-foreground" },
  running: { label: "Processando", className: "text-primary" },
  done: { label: "Concluído", className: "text-success" },
  failed: { label: "Falhou", className: "text-destructive" },
} as const;

/** "0.1" (%) → "10" (basis points), rounded to 0.01 bp without float artefacts. */
function toBps(percent: string): string {
  return String(Math.round(Number(percent) * 10000) / 100);
}

export function BacktestView() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const runId = params.get("run");
  const strategies = useBacktestStrategies();
  const history = useBacktests();
  const run = useBacktest(runId);
  const { remove } = useBacktestMutations();
  const { locale, timeZone } = usePreferences();

  const open = (id: string | null) => router.replace(id ? `${pathname}?run=${id}` : pathname, { scroll: false });

  return (
    <>
      <PageHeader
        title="Estratégias"
        description="Teste regras de entrada e saída no histórico de preços, com custos, sem dados futuros e com validação fora da amostra."
      />
      <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <div className="flex flex-col gap-4">
          <BacktestForm strategies={strategies.data} onCreated={open} />
          <HistoryCard
            items={history.data}
            loading={history.isPending}
            activeId={runId}
            locale={locale}
            timeZone={timeZone}
            strategies={strategies.data}
            onOpen={open}
            onDelete={(id) => {
              remove.mutate(id);
              if (id === runId) open(null);
            }}
          />
        </div>
        <div className="min-w-0">
          {!runId ? (
            <Card>
              <EmptyState
                icon={FlaskConical}
                title="Configure e execute um backtest"
                description="Escolha um ativo e uma estratégia. O resultado mostra o desempenho no treino e na validação, sempre comparado a comprar e manter."
              />
            </Card>
          ) : run.isError ? (
            <Card>
              <ErrorState error={run.error} />
            </Card>
          ) : !run.data ? (
            <Skeleton className="h-96 rounded-xl" />
          ) : run.data.status === "queued" || run.data.status === "running" ? (
            <Card>
              <EmptyState
                icon={Loader2}
                title={run.data.status === "queued" ? "Na fila de processamento" : "Calculando o backtest"}
                description="Cada decisão é recalculada candle a candle; estratégias baseadas nos sinais da Voryn podem levar alguns segundos."
                className="[&_svg]:animate-spin"
              />
            </Card>
          ) : run.data.status === "failed" ? (
            <Card>
              <EmptyState icon={FlaskConical} title="O backtest não pôde ser concluído" description={run.data.error ?? "Tente novamente."} />
            </Card>
          ) : (
            <BacktestResultView run={run.data} strategies={strategies.data} />
          )}
        </div>
      </div>
    </>
  );
}

function BacktestForm({
  strategies,
  onCreated,
}: {
  strategies: BacktestStrategy[] | undefined;
  onCreated: (id: string) => void;
}) {
  const { locale } = usePreferences();
  const { create } = useBacktestMutations();
  const [asset, setAsset] = useState<AssetBrief | null>(null);
  const [strategyKey, setStrategyKey] = useState<StrategyKey>("voryn_signal");
  const [timeframe, setTimeframe] = useState<Timeframe>("1d");
  const [values, setValues] = useState<Record<string, string>>({});
  const [optimize, setOptimize] = useState(false);
  const [fee, setFee] = useState("0,10");
  const [slippage, setSlippage] = useState("0,05");
  const [trainPct, setTrainPct] = useState("70");
  const [error, setError] = useState<string | null>(null);

  const strategy = strategies?.find((s) => s.key === strategyKey);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!asset) return setError("Escolha um ativo.");
    const feePct = parseDecimalInput(fee, locale);
    const slipPct = parseDecimalInput(slippage, locale);
    if (feePct === null || slipPct === null || Number(feePct) > 1 || Number(slipPct) > 1) {
      return setError("Taxa e slippage devem estar entre 0% e 1%.");
    }
    const parsed: Record<string, number> = {};
    for (const p of strategy?.params ?? []) {
      const raw = values[p.key];
      if (raw === undefined || raw === "") continue;
      const n = Number(raw);
      if (!Number.isInteger(n) || n < p.min || n > p.max) return setError(`${p.label}: inteiro entre ${p.min} e ${p.max}.`);
      parsed[p.key] = n;
    }
    setError(null);
    create.mutate(
      {
        asset_id: asset.id,
        strategy: strategyKey,
        timeframe,
        params: optimize ? {} : parsed,
        optimize: optimize && Boolean(strategy?.optimizable),
        // Percent in the form, basis points in the API.
        fee_bps: toBps(feePct),
        slippage_bps: toBps(slipPct),
        train_pct: Number(trainPct),
      },
      { onSuccess: (r) => onCreated(r.id) },
    );
  };

  const apiError = create.error instanceof ApiError ? create.error.message : create.error ? "Não foi possível iniciar o backtest." : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-heading text-sm font-medium">Novo backtest</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="bt-asset">Ativo</Label>
            <AssetPicker id="bt-asset" value={asset} onChange={setAsset} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="bt-strategy">Estratégia</Label>
            <Select value={strategyKey} onValueChange={(v) => { setStrategyKey(v as StrategyKey); setValues({}); }}>
              <SelectTrigger id="bt-strategy" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(strategies ?? []).map((s) => (
                  <SelectItem key={s.key} value={s.key}>
                    {s.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {strategy && <p className="text-xs text-muted-foreground">{strategy.description}</p>}
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">Intervalo</span>
            <div role="radiogroup" aria-label="Intervalo" className="inline-flex w-fit rounded-lg border border-border bg-surface p-0.5">
              {(["1d", "4h"] as const).map((tf) => (
                <button
                  key={tf}
                  type="button"
                  role="radio"
                  aria-checked={timeframe === tf}
                  onClick={() => setTimeframe(tf)}
                  className={cn("h-8 rounded-md px-3 text-xs font-medium", timeframe === tf ? "bg-card text-foreground ring-1 ring-border-strong" : "text-muted-foreground hover:text-foreground")}
                >
                  {tf === "1d" ? "Diário" : "4 horas"}
                </button>
              ))}
            </div>
          </div>

          {strategy && strategy.params.length > 0 && (
            <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface/60 p-3">
              <label className="flex items-center justify-between gap-3 text-sm">
                <span>
                  Otimizar no treino
                  <span className="block text-xs text-muted-foreground">Testa a grade de parâmetros só no período de treino.</span>
                </span>
                <Switch checked={optimize} onCheckedChange={setOptimize} aria-label="Otimizar parâmetros no treino" />
              </label>
              {!optimize && (
                <div className="grid grid-cols-3 gap-2">
                  {strategy.params.map((p) => (
                    <div key={p.key} className="flex flex-col gap-1">
                      <Label htmlFor={`bt-${p.key}`} className="text-xs text-muted-foreground">
                        {p.label}
                      </Label>
                      <Input
                        id={`bt-${p.key}`}
                        inputMode="numeric"
                        placeholder={String(p.default)}
                        value={values[p.key] ?? ""}
                        onChange={(e) => setValues((v) => ({ ...v, [p.key]: e.target.value }))}
                      />
                    </div>
                  ))}
                </div>
              )}
              {optimize && (
                <p className="text-xs text-muted-foreground">
                  Grade: {strategy.params.map((p) => `${p.label} ${p.grid.join("/")}`).join(" · ")}
                </p>
              )}
            </div>
          )}

          <div className="grid grid-cols-3 gap-2">
            <div className="flex flex-col gap-1">
              <Label htmlFor="bt-fee" className="text-xs text-muted-foreground">Taxa (%)</Label>
              <Input id="bt-fee" inputMode="decimal" value={fee} onChange={(e) => setFee(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="bt-slip" className="text-xs text-muted-foreground">Slippage (%)</Label>
              <Input id="bt-slip" inputMode="decimal" value={slippage} onChange={(e) => setSlippage(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="bt-train" className="text-xs text-muted-foreground">Treino</Label>
              <Select value={trainPct} onValueChange={setTrainPct}>
                <SelectTrigger id="bt-train" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {["60", "70", "80"].map((v) => (
                    <SelectItem key={v} value={v}>
                      {v}%
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {(error || apiError) && <p className="text-xs text-destructive">{error ?? apiError}</p>}
          <Button type="submit" disabled={create.isPending || !strategies}>
            {create.isPending ? <Loader2 className="animate-spin" /> : <Play />} Executar backtest
          </Button>
          <p className="text-[11px] leading-snug text-subtle-foreground">
            Até 1.000 candles da Binance (par USDT). Resultados passados não garantem resultados futuros.
          </p>
        </form>
      </CardContent>
    </Card>
  );
}

function HistoryCard({
  items,
  loading,
  activeId,
  locale,
  timeZone,
  strategies,
  onOpen,
  onDelete,
}: {
  items: BacktestSummary[] | undefined;
  loading: boolean;
  activeId: string | null;
  locale: Locale;
  timeZone: string | undefined;
  strategies: BacktestStrategy[] | undefined;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const label = (key: string) => strategies?.find((s) => s.key === key)?.label ?? key;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-heading text-sm font-medium">Histórico</CardTitle>
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-24 w-full" />
        ) : !items?.length ? (
          <p className="text-sm text-muted-foreground">Seus backtests aparecem aqui.</p>
        ) : (
          <ul className="-mx-2 space-y-1">
            {items.map((r) => (
              <li key={r.id} className="group relative">
                <button
                  type="button"
                  onClick={() => onOpen(r.id)}
                  aria-current={r.id === activeId ? "page" : undefined}
                  className={cn("flex w-full items-center gap-2.5 rounded-lg px-2 py-2 pr-9 text-left hover:bg-surface", r.id === activeId && "bg-surface ring-1 ring-border")}
                >
                  <AssetIcon src={r.asset.image_url} symbol={r.asset.symbol} size={22} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-foreground">
                      {r.asset.symbol} · {label(r.strategy)}
                    </span>
                    <span className="block text-xs text-muted-foreground">
                      {r.timeframe === "1d" ? "Diário" : "4h"} · {formatDateTime(r.created_at, locale, timeZone, { dateStyle: "short", timeStyle: "short" })}
                    </span>
                  </span>
                  <span className="num shrink-0 text-right text-xs">
                    {r.status === "done" ? (
                      <>
                        <span className="block text-foreground">{formatPercent(r.validation_return_pct, locale, 1)}</span>
                        <span className="block text-muted-foreground">B&H {formatPercent(r.benchmark_return_pct, locale, 1)}</span>
                      </>
                    ) : (
                      <span className={STATUS[r.status].className}>{STATUS[r.status].label}</span>
                    )}
                  </span>
                </button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Excluir backtest de ${r.asset.symbol}`}
                  onClick={() => onDelete(r.id)}
                  className="absolute top-1/2 right-1 -translate-y-1/2 text-muted-foreground opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                >
                  <Trash2 />
                </Button>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-[11px] text-subtle-foreground">Retorno na validação vs. comprar e manter (B&H) no mesmo período.</p>
      </CardContent>
    </Card>
  );
}
