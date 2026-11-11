"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useMemo } from "react";

import { OpportunityTabs } from "@/components/opportunities/market-tabs";
import { OpportunitiesBoard } from "@/components/opportunities/opportunities-board";
import { Segmented } from "@/components/ui/segmented";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useWatchlists } from "@/lib/analysis-queries";
import type { Timeframe } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { toOpportunity } from "@/lib/opportunity";
import { usePreferences } from "@/lib/queries";
import { useSignals } from "@/lib/signal-queries";

const ALL = "all";

/** Crypto opportunities: the same board as B3, plus timeframe and watchlist. */
export function OpportunitiesView() {
  const { locale, timeZone } = usePreferences();
  const params = useSearchParams();
  const pathname = usePathname();
  const timeframe: Timeframe = params.get("tf") === "4h" ? "4h" : "1d";
  const watchlists = useWatchlists();
  const listId = params.get("lista") ?? undefined;
  const validList = watchlists.data?.some((w) => w.id === listId) ? listId : undefined;
  const query = useSignals(timeframe, validList);
  const items = useMemo(() => query.data?.items.map(toOpportunity), [query.data]);
  const latest = query.data?.items.reduce<string | null>((max, s) => (!max || s.generated_at > max ? s.generated_at : max), null);

  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(window.location.search);
    for (const [k, v] of Object.entries(changes)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    window.history.replaceState(null, "", `${pathname}${next.size ? `?${next}` : ""}`);
  };

  return (
    <OpportunitiesBoard
      title="Oportunidades"
      description="Sinais quantitativos para as principais criptomoedas e as que você acompanha, com score, evidências, riscos e condição de invalidação."
      noun="criptoativos"
      items={items}
      error={query.error}
      onRetry={() => query.refetch()}
      locale={locale}
      tabs={<OpportunityTabs current="crypto" />}
      meta={latest ? <span>Atualizado em {formatDateTime(latest, locale, timeZone, { dateStyle: "short", timeStyle: "short" })}</span> : null}
      limits={
        query.data
          ? `${query.data.disclaimer} Estratégia ${query.data.strategy.name}: score ≥ ${query.data.strategy.buy_threshold} indica potencial de compra; ≤ ${query.data.strategy.sell_threshold}, potencial de venda.`
          : "Carregando…"
      }
      toolbarExtra={
        <>
          <Segmented
            label="Intervalo"
            value={timeframe}
            onChange={(tf) => update({ tf: tf === "1d" ? null : tf, ativo: null })}
            options={[
              { value: "1d", label: "Diário" },
              { value: "4h", label: "4 horas" },
            ]}
          />
          <Select value={validList ?? ALL} onValueChange={(v) => update({ lista: v === ALL ? null : v, ativo: null })}>
            <SelectTrigger className="h-10 w-44 rounded-[10px] bg-surface" aria-label="Lista">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Todos os ativos</SelectItem>
              {watchlists.data?.map((w) => (
                <SelectItem key={w.id} value={w.id}>
                  {w.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </>
      }
      footnote="Score mede a força da evidência (0–100); o sinal indica a direção. Não é recomendação de investimento."
    />
  );
}
