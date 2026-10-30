"use client";

import { cn } from "cn";

import { ChangeBadge } from "@/components/common/change-badge";
import { StatCard } from "@/components/common/stat-card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Locale, Performance, PortfolioSummary } from "@/lib/api/types";
import { formatMoney, formatPercent, trendOf } from "@/lib/format";

const TREND = { up: "text-success", down: "text-destructive", flat: "text-foreground" } as const;

function SignedMoney({ value, summary, locale }: { value: string; summary: PortfolioSummary; locale: Locale }) {
  const trend = trendOf(value);
  const text = formatMoney(value, summary.currency, locale);
  return <span className={TREND[trend]}>{trend === "up" ? `+${text}` : text}</span>;
}

export function SummaryCards({
  summary,
  performance,
  locale,
  loading,
}: {
  summary: PortfolioSummary | undefined;
  performance: Performance | undefined;
  locale: Locale;
  loading: boolean;
}) {
  const s = summary;
  const other = s?.currency === "BRL" ? "USD" : "BRL";
  const otherValue = s ? (other === "USD" ? s.market_value_usd : s.market_value_brl) : null;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard
        label="Patrimônio"
        loading={loading || !s}
        value={s && formatMoney(s.market_value, s.currency, locale)}
        footer={s && otherValue && `${formatMoney(otherValue, other, locale)} · ${s.positions.length} ativo(s)`}
        hint="Valor de mercado das posições abertas a preços atuais."
      />
      <StatCard
        label="Resultado acumulado"
        loading={loading || !s}
        hint="Realizado (vendas, conversões e taxas) + não realizado (valor atual − custo de aquisição)."
        value={s && <SignedMoney value={s.total_pnl} summary={s} locale={locale} />}
        footer={
          s && (
            <span className="flex flex-wrap gap-x-3">
              <span>
                Não realizado <SignedMoney value={s.unrealized_pnl} summary={s} locale={locale} />
              </span>
              <span>
                Realizado <SignedMoney value={s.realized_pnl} summary={s} locale={locale} />
              </span>
            </span>
          )
        }
      />
      <StatCard
        label="Variação em 24 horas"
        loading={loading || !s}
        hint="Diferença do patrimônio em 24h, separando o efeito de mercado dos aportes e retiradas do período."
        value={
          s && (
            <span className="flex items-baseline gap-2">
              <SignedMoney value={s.change_24h.market_effect} summary={s} locale={locale} />
              <ChangeBadge value={s.change_24h.pct} locale={locale} className="text-sm" />
            </span>
          )
        }
        footer={
          s &&
          (Number(s.change_24h.net_flows) !== 0
            ? `Efeito de mercado · aportes líquidos ${formatMoney(s.change_24h.net_flows, s.currency, locale)}`
            : "Efeito de mercado · sem aportes no período")
        }
      />
      <ReturnsCard performance={performance} locale={locale} loading={loading} />
    </div>
  );
}

const PERIODS = [
  ["d1", "24h"],
  ["d7", "7d"],
  ["d30", "30d"],
  ["d90", "90d"],
  ["y1", "1a"],
  ["inception", "Início"],
] as const;

function ReturnsCard({
  performance,
  locale,
  loading,
}: {
  performance: Performance | undefined;
  locale: Locale;
  loading: boolean;
}) {
  return (
    <StatCard
      label="Rentabilidade (TWR)"
      loading={loading || !performance}
      hint="Retorno ponderado pelo tempo: mede o desempenho dos ativos sem a distorção de aportes e retiradas. “—” indica que a carteira ainda não tem o período completo."
      value={
        performance && (
          <span className={cn(TREND[trendOf(performance.returns.inception)])}>
            {formatPercent(performance.returns.inception, locale)}
            <span className="ml-1.5 text-xs font-normal text-muted-foreground">desde o início</span>
          </span>
        )
      }
      footer={
        performance && (
          <div className="space-y-2">
            <div className="num grid grid-cols-5 gap-1">
              {PERIODS.slice(0, 5).map(([key, label]) => (
                <div key={key} className="rounded-md bg-surface px-1 py-1 text-center">
                  <div className="text-[10px] text-subtle-foreground">{label}</div>
                  <div className={cn("text-[11px] font-medium", TREND[trendOf(performance.returns[key])])}>
                    {performance.returns[key] === null ? "—" : formatPercent(performance.returns[key], locale, 1)}
                  </div>
                </div>
              ))}
            </div>
            <Tooltip>
              <TooltipTrigger className="text-left text-[11px] text-muted-foreground underline decoration-dotted underline-offset-2">
                XIRR:{" "}
                {performance.xirr_applicable
                  ? `${formatPercent(performance.xirr_pct, locale)} ao ano`
                  : "disponível após 30 dias"}
              </TooltipTrigger>
              <TooltipContent className="max-w-64">
                Taxa interna de retorno anualizada considerando o valor e a data de cada aporte e
                retirada — reflete o resultado das suas decisões de timing.
              </TooltipContent>
            </Tooltip>
          </div>
        )
      }
    />
  );
}
