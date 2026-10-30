"use client";

import { cn } from "cn";
import { BellRing, ChevronRight, CircleCheck, Info, ShieldAlert, TriangleAlert } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { AssetIcon } from "@/components/common/asset-icon";
import { Hint } from "@/components/common/hint";
import { Skeleton } from "@/components/ui/skeleton";
import type { Insight, Position, Signal } from "@/lib/api/types";
import { SIGNAL_META, useNotifications, useSignals } from "@/lib/signal-queries";

/** Most decisive first: a sell signal on a holding matters more than a buy one. */
const SIGNAL_ORDER = { sell_potential: 0, attention: 1, buy_potential: 2, neutral: 3 } as const;
const INSIGHT_ICON = { info: Info, attention: TriangleAlert, risk: ShieldAlert } as const;

/**
 * "What needs my attention?" for the dashboard, from data the app already has: today's
 * signal on each asset the user holds (only when it is not neutral, or its data is not
 * reliable), alerts that fired and the portfolio insights. Nothing new is computed.
 */
export function AttentionPanel({
  positions,
  insights,
  insightsLoading,
}: {
  positions: Position[] | undefined;
  insights: Insight[] | undefined;
  insightsLoading: boolean;
}) {
  const signals = useSignals("1d");
  const notifications = useNotifications(10);
  const held = new Set(positions?.map((p) => p.asset.id));
  const flagged = (signals.data?.items ?? [])
    .filter((s) => held.has(s.asset.id) && (s.classification !== "neutral" || s.data_quality !== "valid"))
    .sort((a, b) => SIGNAL_ORDER[a.classification] - SIGNAL_ORDER[b.classification]);
  const unread = notifications.data?.unread ?? 0;
  const loading = signals.isPending || insightsLoading || !positions;
  const empty = !loading && flagged.length === 0 && unread === 0 && (insights?.length ?? 0) === 0;

  return (
    <section aria-labelledby="attention-title" className="rounded-2xl border border-border bg-card">
      <header className="flex items-center justify-between gap-2 px-5 pt-4 pb-2">
        <h2 id="attention-title" className="font-heading text-sm font-medium">
          Precisa da sua atenção
        </h2>
        <Hint
          label="Precisa da sua atenção"
          content="Sinais diários dos ativos que você tem (exceto neutros), alertas disparados e os insights da carteira. Sinais são análises, não recomendações de investimento."
        />
      </header>

      {loading ? (
        <div className="space-y-2 px-5 pb-5">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      ) : empty ? (
        <p className="flex items-start gap-2 px-5 pb-5 text-sm text-muted-foreground">
          <CircleCheck className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
          Nada fora do comum nos seus ativos agora.
        </p>
      ) : (
        <ul className="divide-y divide-border px-2 pb-2">
          {unread > 0 && (
            <Row
              href="/alertas"
              icon={<BellRing className="size-4 text-primary-ink" aria-hidden />}
              title={unread === 1 ? "1 alerta disparado" : `${unread} alertas disparados`}
              detail="Toque para ver as notificações"
            />
          )}
          {flagged.map((s) => (
            <SignalRow key={s.id} signal={s} />
          ))}
          {insights?.map((item) => {
            const Icon = INSIGHT_ICON[item.severity];
            return (
              <Row
                key={item.id}
                href="/carteira"
                icon={
                  <Icon
                    className={cn(
                      "size-4",
                      item.severity === "risk" ? "text-destructive" : item.severity === "attention" ? "text-warning" : "text-primary-ink",
                    )}
                    aria-hidden
                  />
                }
                title={item.title}
                detail={item.message}
              />
            );
          })}
        </ul>
      )}
    </section>
  );
}

function SignalRow({ signal: s }: { signal: Signal }) {
  const meta = SIGNAL_META[s.classification];
  const quality = s.data_quality !== "valid";
  return (
    <Row
      href={`/analise/${s.asset.slug}`}
      icon={<AssetIcon src={s.asset.image_url} symbol={s.asset.symbol} size={28} />}
      title={
        <>
          {s.asset.name}{" "}
          <span className={cn("ml-1 inline-flex rounded-md border px-1.5 py-px text-[11px] font-medium", meta.tone)}>
            {meta.label}
          </span>
        </>
      }
      detail={quality ? "Dados com problema: sinal suspenso" : `Score ${Number(s.score).toFixed(0)} de 100 · sinal diário`}
    />
  );
}

function Row({ href, icon, title, detail }: { href: string; icon: ReactNode; title: ReactNode; detail: ReactNode }) {
  return (
    <li>
      <Link
        href={href}
        className="flex min-h-14 items-center gap-3 rounded-xl px-3 py-2.5 transition-colors outline-none hover:bg-card-hover focus-visible:ring-2 focus-visible:ring-ring/70"
      >
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-surface">{icon}</span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-foreground">{title}</span>
          <span className="mt-0.5 line-clamp-2 block text-xs text-muted-foreground">{detail}</span>
        </span>
        <ChevronRight className="size-4 shrink-0 text-subtle-foreground" aria-hidden />
      </Link>
    </li>
  );
}
