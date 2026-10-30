"use client";

import { cn } from "cn";
import { FlaskConical, ShieldHalf } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AssetIcon } from "@/components/common/asset-icon";
import { PageHeader } from "@/components/common/page-header";
import { StatCard } from "@/components/common/stat-card";
import { EmptyState, ErrorState } from "@/components/common/states";
import { InsightsPanel } from "@/components/portfolio/insights-panel";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api/client";
import type { AssetRisk, Currency, Locale, Risk, Scenario, ScenarioMethod } from "@/lib/api/types";
import { formatDateTime, formatMoney, formatNumber, formatPercent, parseDecimalInput, trendOf } from "@/lib/format";
import { usePortfolio } from "@/lib/portfolio-queries";
import { usePreferences } from "@/lib/queries";
import { RISK_WINDOWS, useRisk, useScenario, type RiskWindowDays } from "@/lib/risk-queries";

const LIQUIDITY = {
  high: { label: "Alta", className: "text-success" },
  medium: { label: "Média", className: "text-warning" },
  low: { label: "Baixa", className: "text-destructive" },
  unknown: { label: "Sem dados", className: "text-muted-foreground" },
} as const;

const METHOD: Record<ScenarioMethod, string> = {
  beta: "Pelo beta",
  stablecoin: "Stablecoin",
  override: "Manual",
  assumed_beta_1: "Igual ao BTC",
};

const PRESETS = ["-50", "-30", "-10", "10", "30"];
const TREND = { up: "text-success", down: "text-destructive", flat: "text-muted-foreground" } as const;

/** Signed decimal typed by the user ("-30", "−12,5") as an API decimal string, or null. */
function parseSigned(raw: string, locale: Locale): string | null {
  const trimmed = raw.trim();
  const negative = /^[-−]/.test(trimmed);
  const parsed = parseDecimalInput(trimmed.replace(/^[-−+]/, ""), locale);
  if (parsed === null) return null;
  return negative && Number(parsed) !== 0 ? `-${parsed}` : parsed;
}

function day(iso: string | null | undefined, locale: Locale): string {
  return iso ? formatDateTime(`${iso}T12:00:00Z`, locale, "UTC", { dateStyle: "short" }) : "—";
}

export function RiskView() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const raw = Number(params.get("janela"));
  const window: RiskWindowDays = (RISK_WINDOWS as readonly number[]).includes(raw) ? (raw as RiskWindowDays) : 365;
  const { currency, locale, timeZone } = usePreferences();
  const portfolio = usePortfolio();
  const risk = useRisk(portfolio.data?.id, window);
  const data = risk.data;

  const setWindow = (w: RiskWindowDays) => {
    router.replace(w === 365 ? pathname : `${pathname}?janela=${w}`, { scroll: false });
  };

  const header = (
    <PageHeader
      title="Risco"
      description="Como a sua carteira de hoje teria se comportado no histórico recente: oscilação, perdas extremas, concentração e liquidez."
      actions={
        <div role="radiogroup" aria-label="Período" className="inline-flex rounded-lg border border-border bg-surface p-0.5">
          {RISK_WINDOWS.map((w) => (
            <button
              key={w}
              type="button"
              role="radio"
              aria-checked={window === w}
              onClick={() => setWindow(w)}
              className={cn(
                "h-8 rounded-md px-3 text-xs font-medium",
                window === w ? "bg-card text-foreground ring-1 ring-border-strong" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {w === 365 ? "1 ano" : `${w} dias`}
            </button>
          ))}
        </div>
      }
    />
  );

  if (risk.isError) {
    return (
      <>
        {header}
        <Card>
          <ErrorState error={risk.error} onRetry={() => void risk.refetch()} />
        </Card>
      </>
    );
  }
  if (data && data.assets.length === 0) {
    return (
      <>
        {header}
        <Card>
          <EmptyState
            icon={ShieldHalf}
            title="Sem posições para analisar"
            description="Registre suas transações para ver a volatilidade, o VaR e os cenários da sua carteira."
            action={
              <Button asChild variant="outline" size="sm">
                <Link href="/carteira">Ir para a carteira</Link>
              </Button>
            }
          />
        </Card>
      </>
    );
  }

  const loading = !data;
  const [var95, var99] = data?.var ?? [];
  const money = (v: string | null | undefined) => formatMoney(v, currency, locale);

  return (
    <>
      {header}
      {data && (
        <p className="mb-4 text-xs text-muted-foreground">
          {data.period_start
            ? `Período: ${day(data.period_start, locale)} a ${day(data.period_end, locale)} · ${data.observations} retornos diários`
            : "Histórico insuficiente (mínimo de 30 dias em comum entre os ativos)"}
          {" · "}
          Cobertura {formatNumber(data.coverage_pct, locale, { digits: 1 })}% da carteira · {data.data_source} ·
          dados de {formatDateTime(data.as_of, locale, timeZone)}
        </p>
      )}

      <div className="grid grid-cols-2 gap-3 md:gap-4 xl:grid-cols-4">
        <StatCard
          label="Volatilidade anualizada"
          hint="Desvio-padrão dos retornos diários × √365, com os pesos atuais."
          loading={loading}
          value={data?.volatility_pct ? `${formatNumber(data.volatility_pct, locale, { digits: 1 })}%` : "—"}
          footer={data?.beta_btc ? `Beta ao BTC: ${formatNumber(data.beta_btc, locale)}` : undefined}
        />
        <StatCard
          label="VaR 95% · 1 dia"
          hint="Perda diária que só foi superada em 5% dos dias do período (VaR histórico). Não é a perda máxima possível."
          loading={loading}
          value={var95?.amount ? money(var95.amount) : "—"}
          footer={var95?.pct ? `${formatNumber(var95.pct, locale)}% · VaR 99%: ${formatNumber(var99?.pct, locale)}%` : undefined}
        />
        <StatCard
          label="Perda média nos piores dias"
          hint="Expected shortfall 95%: média das perdas nos dias além do VaR 95%."
          loading={loading}
          value={data?.expected_shortfall_95.amount ? money(data.expected_shortfall_95.amount) : "—"}
          footer={data?.expected_shortfall_95.pct ? `${formatNumber(data.expected_shortfall_95.pct, locale)}% em um dia` : undefined}
        />
        <StatCard
          label="Drawdown máximo"
          hint="Maior queda do pico ao vale das quantidades atuais ao longo do período."
          loading={loading}
          value={data?.drawdown.pct ? formatPercent(data.drawdown.pct, locale, 1) : "—"}
          footer={
            data?.drawdown.peak
              ? `${day(data.drawdown.peak, locale)} → ${day(data.drawdown.trough, locale)} · hoje ${formatPercent(data.drawdown.current_pct, locale, 1)}`
              : undefined
          }
        />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <InsightsPanel
            title="Pontos de atenção"
            items={data?.flags}
            loading={loading}
            emptyText="Nenhum ponto de atenção pelas regras de risco atuais (volatilidade, drawdown, diversificação, liquidez e correlação)."
          />
        </div>
        <StressCard data={data} currency={currency} locale={locale} />
      </div>

      <AssetTable data={data} currency={currency} locale={locale} />

      <div className="mt-4 grid gap-4 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <ScenarioCard portfolioId={portfolio.data?.id} window={window} assets={data?.assets} currency={currency} locale={locale} />
        </div>
        <div className="lg:col-span-2">
          <CorrelationCard data={data} locale={locale} />
        </div>
      </div>

      {data && (
        <details className="mt-4 rounded-xl border border-border bg-card px-5 py-4 text-sm">
          <summary className="cursor-pointer font-medium text-foreground">Metodologia</summary>
          <ul className="mt-3 list-disc space-y-1.5 pl-5 text-muted-foreground">
            {data.methodology.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}

function StressCard({ data, currency, locale }: { data: Risk | undefined; currency: Currency; locale: Locale }) {
  const rows = data ? [data.worst_day, ...data.stress].filter((s) => s !== null) : [];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-heading text-sm font-medium">Piores momentos do período</CardTitle>
      </CardHeader>
      <CardContent>
        {!data ? (
          <Skeleton className="h-28 w-full" />
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">Histórico insuficiente.</p>
        ) : (
          <ul className="space-y-3">
            {rows.map((s) => (
              <li key={s.days} className="flex items-baseline justify-between gap-3">
                <div>
                  <p className="text-sm text-foreground">{s.days === 1 ? "Pior dia" : `Piores ${s.days} dias`}</p>
                  <p className="text-xs text-muted-foreground">
                    {day(s.start, locale)} → {day(s.end, locale)}
                  </p>
                </div>
                <div className="num text-right">
                  <p className="text-sm font-medium text-destructive">{formatPercent(s.pct, locale, 1)}</p>
                  <p className="text-xs text-muted-foreground">{formatMoney(s.amount, currency, locale)} hoje</p>
                </div>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-[11px] text-subtle-foreground">Variação das quantidades atuais nessas datas, aplicada ao valor de hoje.</p>
      </CardContent>
    </Card>
  );
}

function AssetTable({ data, currency, locale }: { data: Risk | undefined; currency: Currency; locale: Locale }) {
  const pct = (v: string | null, digits = 1) => (v === null ? "—" : `${formatNumber(v, locale, { digits })}%`);
  return (
    <Card className="mt-4 gap-0 py-0">
      <CardHeader className="py-4">
        <CardTitle className="font-heading text-sm font-medium">Risco por ativo</CardTitle>
      </CardHeader>
      {!data ? (
        <div className="px-5 pb-5">
          <Skeleton className="h-40 w-full" />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-sm">
            <thead className="border-y border-border bg-surface text-xs text-muted-foreground">
              <tr>
                <th className="px-5 py-2.5 text-left font-medium">Ativo</th>
                <th className="px-3 py-2.5 text-right font-medium">Peso</th>
                <th className="px-3 py-2.5 text-right font-medium">Volatilidade</th>
                <th className="px-3 py-2.5 text-right font-medium">Drawdown máx.</th>
                <th className="px-3 py-2.5 text-right font-medium">Beta BTC</th>
                <th className="px-3 py-2.5 text-right font-medium">VaR 95%</th>
                <th className="px-3 py-2.5 text-right font-medium">
                  <Hint label="Contribuição" text="Parcela da volatilidade da carteira que vem deste ativo (soma 100%)." />
                </th>
                <th className="px-5 py-2.5 text-right font-medium">
                  <Hint label="Liquidez" text="Valor da posição ÷ volume médio diário de 30 dias no par USDT da Binance." />
                </th>
              </tr>
            </thead>
            <tbody className="num">
              {data.assets.map((a) => (
                <AssetRow key={a.asset.id} a={a} currency={currency} locale={locale} pct={pct} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function AssetRow({
  a,
  currency,
  locale,
  pct,
}: {
  a: AssetRisk;
  currency: Currency;
  locale: Locale;
  pct: (v: string | null, digits?: number) => string;
}) {
  const liquidity = LIQUIDITY[a.liquidity];
  return (
    <tr className="border-b border-border last:border-0">
      <td className="px-5 py-3">
        <div className="flex items-center gap-2.5">
          <AssetIcon src={a.asset.image_url} symbol={a.asset.symbol} size={24} />
          <div className="min-w-0">
            <p className="font-medium text-foreground">{a.asset.symbol}</p>
            <p className="text-xs text-muted-foreground">
              {formatMoney(a.market_value, currency, locale)}
              {a.is_stablecoin && " · stablecoin"}
              {!a.covered && " · sem histórico"}
            </p>
          </div>
        </div>
      </td>
      <td className="px-3 py-3 text-right">{pct(a.weight_pct)}</td>
      <td className="px-3 py-3 text-right">{pct(a.volatility_pct)}</td>
      <td className="px-3 py-3 text-right">{a.max_drawdown_pct === null ? "—" : formatPercent(a.max_drawdown_pct, locale, 1)}</td>
      <td className="px-3 py-3 text-right">{a.beta_btc === null ? "—" : formatNumber(a.beta_btc, locale)}</td>
      <td className="px-3 py-3 text-right">{pct(a.var95_pct)}</td>
      <td className="px-3 py-3 text-right">{pct(a.risk_contribution_pct)}</td>
      <td className="px-5 py-3 text-right">
        <span className={liquidity.className}>{liquidity.label}</span>
        {a.position_to_volume_pct !== null && !a.is_stablecoin && (
          <span className="block text-xs text-muted-foreground">{formatNumber(a.position_to_volume_pct, locale, { digits: 3 })}% do volume</span>
        )}
      </td>
    </tr>
  );
}

function Hint({ label, text }: { label: string; text: string }) {
  return (
    <Tooltip>
      <TooltipTrigger className="underline decoration-dotted underline-offset-2">{label}</TooltipTrigger>
      <TooltipContent className="max-w-64">{text}</TooltipContent>
    </Tooltip>
  );
}

function CorrelationCard({ data, locale }: { data: Risk | undefined; locale: Locale }) {
  const symbols = data?.correlation.symbols ?? [];
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="font-heading text-sm font-medium">Correlação dos retornos diários</CardTitle>
      </CardHeader>
      <CardContent>
        {!data ? (
          <Skeleton className="h-40 w-full" />
        ) : symbols.length < 2 ? (
          <p className="text-sm text-muted-foreground">É preciso ao menos dois ativos com histórico (stablecoins não entram).</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="num mx-auto text-xs" aria-label="Matriz de correlação">
              <thead>
                <tr>
                  <th />
                  {symbols.map((s) => (
                    <th key={s} className="px-1 pb-1.5 font-medium text-muted-foreground">
                      {s}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.correlation.values.map((row, i) => (
                  <tr key={symbols[i]}>
                    <th className="pr-2 text-right font-medium text-muted-foreground">{symbols[i]}</th>
                    {row.map((rho, j) => {
                      const n = rho === null ? null : Number(rho);
                      const color = n === null ? undefined : n >= 0 ? `rgba(99,102,241,${0.12 + n * 0.55})` : `rgba(34,197,94,${0.12 - n * 0.55})`;
                      return (
                        <td key={symbols[j]} className="p-0.5">
                          <span
                            className="flex size-11 items-center justify-center rounded-md text-foreground"
                            style={{ backgroundColor: color }}
                            title={`${symbols[i]} × ${symbols[j]}`}
                          >
                            {n === null ? "—" : formatNumber(n, locale)}
                          </span>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-3 text-[11px] text-subtle-foreground">
          1 = movem-se juntos; 0 = sem relação; negativo = em sentidos opostos.
        </p>
      </CardContent>
    </Card>
  );
}

function ScenarioCard({
  portfolioId,
  window,
  assets,
  currency,
  locale,
}: {
  portfolioId: string | undefined;
  window: RiskWindowDays;
  assets: AssetRisk[] | undefined;
  currency: Currency;
  locale: Locale;
}) {
  const scenario = useScenario(portfolioId);
  const [btc, setBtc] = useState("-30");
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const run = (value = btc) => {
    const btcPct = parseSigned(value, locale);
    if (btcPct === null || Number(btcPct) < -100) {
      setError("Informe a variação do Bitcoin em % (mínimo −100).");
      return;
    }
    const parsed = Object.entries(overrides)
      .filter(([, v]) => v.trim())
      .map(([asset_id, v]) => ({ asset_id, change_pct: parseSigned(v, locale) }));
    if (parsed.some((o) => o.change_pct === null || Number(o.change_pct) < -100)) {
      setError("Revise as variações manuais (números em %, mínimo −100).");
      return;
    }
    setError(null);
    scenario.mutate({
      btc_change_pct: btcPct,
      window,
      overrides: parsed.map((o) => ({ asset_id: o.asset_id, change_pct: o.change_pct as string })),
    });
  };
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    run();
  };

  const result: Scenario | undefined = scenario.data;
  const apiError = scenario.error instanceof ApiError ? scenario.error.message : scenario.error ? "Não foi possível simular." : null;

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 font-heading text-sm font-medium">
          <FlaskConical className="size-4 text-primary" aria-hidden /> Simulador de cenários
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Variação do Bitcoin (%)
            <Input
              value={btc}
              onChange={(e) => setBtc(e.target.value)}
              inputMode="decimal"
              className="w-28"
              aria-label="Variação do Bitcoin em porcentagem"
            />
          </label>
          <div className="flex flex-wrap gap-1.5">
            {PRESETS.map((p) => (
              <Button
                key={p}
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setBtc(p);
                  run(p);
                }}
              >
                {Number(p) > 0 ? `+${p}%` : `${p.replace("-", "−")}%`}
              </Button>
            ))}
          </div>
          <Button type="submit" size="sm" disabled={!portfolioId || scenario.isPending}>
            Simular
          </Button>
        </form>
        {(error || apiError) && <p className="mt-2 text-xs text-destructive">{error ?? apiError}</p>}

        {result && (
          <div className="mt-4">
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
              <p className="num font-heading text-xl font-semibold text-foreground">{formatMoney(result.new_value, currency, locale)}</p>
              <p className={cn("num text-sm font-medium", TREND[trendOf(result.pnl)])}>
                {formatMoney(result.pnl, currency, locale)} ({formatPercent(result.pnl_pct, locale)})
              </p>
              <p className="text-xs text-muted-foreground">hoje: {formatMoney(result.market_value, currency, locale)}</p>
            </div>
            <div className="mt-3 overflow-x-auto">
              <table className="num w-full min-w-[520px] text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="py-2 text-left font-medium">Ativo</th>
                    <th className="py-2 text-right font-medium">Variação</th>
                    <th className="py-2 text-right font-medium">Resultado</th>
                    <th className="py-2 pl-3 text-right font-medium">Ajuste manual (%)</th>
                  </tr>
                </thead>
                <tbody>
                  {result.lines.map((ln) => (
                    <tr key={ln.asset.id} className="border-b border-border last:border-0">
                      <td className="py-2">
                        <span className="font-medium text-foreground">{ln.asset.symbol}</span>
                        <span className="ml-2 text-xs text-muted-foreground">{METHOD[ln.method]}</span>
                      </td>
                      <td className="py-2 text-right">{formatPercent(ln.change_pct, locale, 1)}</td>
                      <td className={cn("py-2 text-right", TREND[trendOf(ln.pnl)])}>{formatMoney(ln.pnl, currency, locale)}</td>
                      <td className="py-2 pl-3 text-right">
                        <Input
                          value={overrides[ln.asset.id] ?? ""}
                          onChange={(e) => setOverrides((o) => ({ ...o, [ln.asset.id]: e.target.value }))}
                          onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), run())}
                          placeholder="—"
                          inputMode="decimal"
                          className="ml-auto h-7 w-20 text-right"
                          aria-label={`Variação manual de ${ln.asset.symbol}`}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul className="mt-3 space-y-1 text-[11px] text-subtle-foreground">
              {result.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </div>
        )}
        {!result && assets && (
          <p className="mt-3 text-xs text-muted-foreground">
            Aplica uma variação do Bitcoin às suas {assets.length} posições, pelo beta histórico de cada ativo. Simulação
            mecânica, não previsão.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
