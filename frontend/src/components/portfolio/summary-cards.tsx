"use client";

import { cn } from "cn";
import type { ReactNode } from "react";

import { ChangeBadge } from "@/components/common/change-badge";
import { Hint } from "@/components/common/hint";
import { Skeleton } from "@/components/ui/skeleton";
import type { Locale, Performance, PortfolioSummary } from "@/lib/api/types";
import { formatMoney, formatPercent, trendOf } from "@/lib/format";

const TREND = { up: "text-success", down: "text-destructive", flat: "text-foreground" } as const;

function SignedMoney({ value, summary, locale }: { value: string; summary: PortfolioSummary; locale: Locale }) {
  const trend = trendOf(value);
  const text = formatMoney(value, summary.currency, locale);
  return <span className={TREND[trend]}>{trend === "up" ? `+${text}` : text}</span>;
}

const PERIODS = [
  ["d1", "24h"],
  ["d7", "7d"],
  ["d30", "30d"],
  ["d90", "90d"],
  ["y1", "1a"],
] as const;

/**
 * The portfolio at a glance, ordered by what people look for first: how much it is worth,
 * how it moved today, then the result and the return. One surface instead of four cards,
 * so the value reads first and the chart fits on the first screen of a phone.
 * Figures come straight from the summary and performance endpoints; nothing is computed here.
 */
export function SummaryCards({
  summary: s,
  performance,
  locale,
  loading,
}: {
  summary: PortfolioSummary | undefined;
  performance: Performance | undefined;
  locale: Locale;
  loading: boolean;
}) {
  const other = s?.currency === "BRL" ? "USD" : "BRL";
  const otherValue = s ? (other === "USD" ? s.market_value_usd : s.market_value_brl) : null;
  const flows = s ? Number(s.change_24h.net_flows) : 0;

  return (
    // The value sits on the page itself, unframed, as the most important thing on screen;
    // the supporting figures are grouped in one quiet surface beside (desktop) or below it.
    <section aria-label="Resumo da carteira" className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between lg:gap-10">
      <div className="min-w-0 px-1">
        <Label hint="Valor de mercado das posições abertas a preços atuais.">Patrimônio</Label>
        {loading || !s ? (
          <Skeleton className="mt-2 h-12 w-64" />
        ) : (
          <p className="num mt-1 font-heading text-[2.625rem] leading-[1.05] font-semibold tracking-[-0.035em] text-foreground md:text-[3.25rem]">
            {formatMoney(s.market_value, s.currency, locale)}
          </p>
        )}
        {loading || !s ? (
          <Skeleton className="mt-3 h-5 w-64" />
        ) : (
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
            <span className="num inline-flex items-center gap-1.5 font-medium">
              <SignedMoney value={s.change_24h.market_effect} summary={s} locale={locale} />
              <ChangeBadge value={s.change_24h.pct} locale={locale} variant="pill" />
              <span className="font-normal text-muted-foreground">em 24h</span>
              <Hint
                label="Variação em 24 horas"
                content="Diferença do patrimônio em 24h, separando o efeito de mercado dos aportes e retiradas do período."
              />
            </span>
            <span className="num text-muted-foreground">
              {otherValue && `${formatMoney(otherValue, other, locale)} · `}
              {s.positions.length} {s.positions.length === 1 ? "ativo" : "ativos"}
              {flows !== 0 && ` · aportes líquidos ${formatMoney(s.change_24h.net_flows, s.currency, locale)}`}
            </span>
          </div>
        )}
      </div>

      <div className="overflow-hidden rounded-2xl bg-card ring-1 ring-white/6 lg:w-[460px] lg:shrink-0">
        <dl className="grid grid-cols-2 divide-x divide-white/6 px-1 py-4">
          <Metric
            label="Resultado"
            hint="Realizado (vendas, conversões e taxas) + não realizado (valor atual − custo de aquisição)."
            loading={loading || !s}
            value={s && <SignedMoney value={s.total_pnl} summary={s} locale={locale} />}
            detail={
              s && (
                <>
                  Não realizado <SignedMoney value={s.unrealized_pnl} summary={s} locale={locale} />
                  <br />
                  Realizado <SignedMoney value={s.realized_pnl} summary={s} locale={locale} />
                </>
              )
            }
          />
          <Metric
            label="Rentabilidade"
            hint="Retorno ponderado pelo tempo (TWR): mede o desempenho dos ativos sem a distorção de aportes e retiradas."
            loading={!performance}
            value={
              performance && (
                <span className={TREND[trendOf(performance.returns.inception)]}>
                  {formatPercent(performance.returns.inception, locale)}
                </span>
              )
            }
            detail={
              performance && (
                <>
                  desde o início
                  <br />
                  <Hint content="Taxa interna de retorno anualizada considerando o valor e a data de cada aporte e retirada — reflete o resultado das suas decisões de timing.">
                    XIRR{" "}
                    {performance.xirr_applicable
                      ? `${formatPercent(performance.xirr_pct, locale)} ao ano`
                      : "após 30 dias"}
                  </Hint>
                </>
              )
            }
          />
        </dl>

        <div className="border-t border-white/6 px-2">
          {performance ? (
            <dl className="num grid grid-cols-5" aria-label="Rentabilidade por período">
              {PERIODS.map(([key, label]) => {
                const value = performance.returns[key];
                return (
                  <div key={key} className="px-1 py-2.5 text-center">
                    <dt className="text-[11px] text-subtle-foreground">{label}</dt>
                    <dd className={cn("text-[13px] font-medium", TREND[trendOf(value)])}>
                      {value === null ? (
                        <span className="text-subtle-foreground" title="A carteira ainda não tem o período completo">
                          —
                        </span>
                      ) : (
                        formatPercent(value, locale, 1)
                      )}
                    </dd>
                  </div>
                );
              })}
            </dl>
          ) : (
            <Skeleton className="my-3 h-8 w-full" />
          )}
        </div>
      </div>
    </section>
  );
}

function Label({ children, hint }: { children: ReactNode; hint: string }) {
  return (
    <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
      {children}
      <Hint label={String(children)} content={hint} />
    </p>
  );
}

function Metric({
  label,
  hint,
  value,
  detail,
  loading,
}: {
  label: string;
  hint: string;
  value: ReactNode;
  detail: ReactNode;
  loading: boolean;
}) {
  return (
    <div className="min-w-0 px-4">
      <dt className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        {label}
        <Hint label={label} content={hint} />
      </dt>
      {loading ? (
        <Skeleton className="mt-2 h-6 w-28" />
      ) : (
        <>
          <dd className="num mt-1 font-heading text-lg font-semibold md:text-xl">{value}</dd>
          <dd className="num mt-1 text-xs leading-relaxed text-muted-foreground">{detail}</dd>
        </>
      )}
    </div>
  );
}
