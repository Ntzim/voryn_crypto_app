"use client";

import { ArrowLeft, ArrowRight, Bell, CircleCheck, Star, TriangleAlert, X } from "lucide-react";
import Link from "next/link";

import { AssetIcon } from "@/components/common/asset-icon";
import { ScoreBar, SignalBadge } from "@/components/signals/signal-primitives";
import { buttonVariants } from "@/components/ui/button";
import type { Locale } from "@/lib/api/types";
import { formatNumber, formatPrice } from "@/lib/format";
import type { Opportunity } from "@/lib/opportunity";

/** Everything the engine says about one asset, in reading order: verdict, levels, evidence, risks. */
export function OpportunityDetail({
  item,
  locale,
  onClose,
  variant = "panel",
}: {
  item: Opportunity;
  locale: Locale;
  onClose: () => void;
  variant?: "panel" | "page";
}) {
  const money = (value: number | null | undefined) => (value === null || value === undefined ? "—" : formatPrice(value, item.currency, locale));
  const crypto = item.market === "CRYPTO";
  return (
    <article aria-label={`Detalhe de ${item.symbol}`} className="flex flex-col gap-5">
      <header className="flex items-center gap-3">
        {variant === "page" && (
          <button type="button" onClick={onClose} aria-label="Voltar para a lista" className="-ml-2 inline-flex size-11 items-center justify-center rounded-[10px] text-muted-foreground hover:text-foreground">
            <ArrowLeft className="size-5" strokeWidth={1.5} />
          </button>
        )}
        <AssetAvatar item={item} size={40} />
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold text-foreground">{item.symbol}</h2>
          <p className="truncate text-xs text-muted-foreground">{item.name}</p>
        </div>
        {variant === "panel" && (
          <button type="button" onClick={onClose} aria-label="Fechar detalhe" className="inline-flex size-10 items-center justify-center rounded-[10px] text-muted-foreground hover:bg-card-hover hover:text-foreground">
            <X className="size-4" strokeWidth={1.5} />
          </button>
        )}
      </header>

      <div
        className="grid grid-cols-2 gap-4 rounded-2xl border border-border p-4"
        style={variant === "page" ? { backgroundImage: "radial-gradient(260px 120px at 100% 0%, var(--brand-glow), transparent 70%)" } : undefined}
      >
        <div className="flex flex-col gap-2">
          <span className="num text-2xl font-bold text-foreground">{money(item.price)}</span>
          <SignalBadge value={item.signal} className="w-fit" />
        </div>
        <div className="flex flex-col items-end gap-2 text-right">
          {item.hasScore ? (
            <>
              <span className="num text-2xl leading-none font-bold text-foreground">
                {formatNumber(item.score, locale, { digits: 0 })}
                <span className="text-xs font-medium text-subtle-foreground"> /100</span>
              </span>
              <ScoreBar score={item.score} className="w-24" />
              <span className="text-[11px] text-subtle-foreground">Força da evidência</span>
            </>
          ) : (
            <span className="text-xs text-subtle-foreground">Sem score: faltam P/VP e rendimentos</span>
          )}
        </div>
      </div>

      {item.dataQuality !== "valid" && (
        <p role="status" className="rounded-[10px] bg-signal-watch-soft p-3 text-xs text-signal-watch">
          {item.qualityReasons[0] ?? "Dados insuficientes."} Compra e venda suspensas.
        </p>
      )}

      <p className="rounded-[10px] bg-background p-3 text-sm text-foreground">{item.summary}</p>

      {variant === "page" && (
        <dl className="grid grid-cols-3 gap-2">
          <Metric label="Tendência" value={item.trend ? `${capitalize(item.trend.direction)} · ${signed(item.trend.saldo)}/${item.trend.total}` : "—"} />
          <Metric label="ATR" value={item.atrPct !== undefined ? `${formatNumber(item.atrPct, locale, { digits: 2 })}%` : "—"} />
          <Metric label="Volatilidade" value={item.volatility ? capitalize(item.volatility.level) : "—"} />
        </dl>
      )}

      <PriceLevels item={item} locale={locale} />

      {item.evidence.length > 0 && (
        <section aria-labelledby={`evidence-${item.id}`}>
          <h3 id={`evidence-${item.id}`} className="eyebrow mb-2 text-subtle-foreground">Evidências</h3>
          <ul className="space-y-2">
            {item.evidence.map((text) => (
              <li key={text} className="flex gap-2 text-sm text-foreground">
                <CircleCheck className="mt-0.5 size-4 shrink-0 text-signal-buy" strokeWidth={1.5} aria-hidden />
                {text}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby={`risks-${item.id}`}>
        <h3 id={`risks-${item.id}`} className="eyebrow mb-2 text-subtle-foreground">Riscos</h3>
        {item.risks.length ? (
          <ul className="space-y-2">
            {item.risks.map((text) => (
              <li key={text} className="flex gap-2 text-sm text-foreground">
                <TriangleAlert className="mt-0.5 size-4 shrink-0 text-signal-watch" strokeWidth={1.5} aria-hidden />
                {text}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">Nenhum risco específico identificado pelas regras; o risco de mercado permanece.</p>
        )}
      </section>

      {item.invalidation && (
        <section className="rounded-[10px] border border-border p-3">
          <h3 className="eyebrow mb-1 text-subtle-foreground">Sinal invalidado se</h3>
          <p className="text-sm font-medium text-foreground">{item.invalidation}</p>
        </section>
      )}

      <div className={variant === "page" ? "fixed inset-x-0 bottom-0 z-40 flex gap-2 border-t border-border bg-bar p-3 pb-safe" : "flex flex-col gap-2"}>
        {crypto && (
          <Link href="/alertas" className={buttonVariants({ className: "h-11 flex-1 rounded-[10px]" })}>
            <Bell className="size-4" strokeWidth={1.5} /> Criar alerta
          </Link>
        )}
        {crypto && variant === "panel" && (
          <Link href={item.href} className={buttonVariants({ variant: "outline", className: "h-11 rounded-[10px]" })}>
            <Star className="size-4" strokeWidth={1.5} /> Acompanhar
          </Link>
        )}
        <Link
          href={item.href}
          className={
            variant === "page" || !crypto
              ? buttonVariants({ variant: crypto ? "outline" : "default", className: "h-11 flex-1 rounded-[10px]" })
              : "inline-flex items-center gap-1 text-sm font-medium text-primary-ink"
          }
        >
          {variant === "page" ? "Análise completa" : `Abrir análise completa de ${item.symbol}`} <ArrowRight className="size-4" strokeWidth={1.5} />
        </Link>
      </div>
    </article>
  );
}

/** Price between support and resistance, only drawn when both exist. */
function PriceLevels({ item, locale }: { item: Opportunity; locale: Locale }) {
  const { support, resistance, price } = item;
  const money = (v: number) => formatPrice(v, item.currency, locale);
  const position =
    support && resistance && price !== null && resistance.value > support.value
      ? Math.max(0, Math.min(100, ((price - support.value) / (resistance.value - support.value)) * 100))
      : null;
  return (
    <section aria-labelledby={`levels-${item.id}`}>
      <h3 id={`levels-${item.id}`} className="eyebrow mb-2 text-subtle-foreground">Níveis de preço</h3>
      {position !== null && (
        <div className="relative mb-3 h-1.5 rounded-full bg-border" aria-hidden>
          <span className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface bg-brand" style={{ left: `${position}%` }} />
        </div>
      )}
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-[10px] bg-background p-3">
          <p className="text-[11px] text-subtle-foreground">Suporte</p>
          {support ? (
            <>
              <p className="num text-sm font-semibold text-foreground">{money(support.value)}</p>
              <p className="num text-[11px] text-muted-foreground">{formatNumber(support.distPct, locale, { digits: 1 })}% abaixo</p>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Não identificado</p>
          )}
        </div>
        <div className="rounded-[10px] bg-background p-3">
          <p className="text-[11px] text-subtle-foreground">Resistência</p>
          {resistance ? (
            <>
              <p className="num text-sm font-semibold text-foreground">{money(resistance.value)}</p>
              <p className="num text-[11px] text-muted-foreground">{formatNumber(resistance.distPct, locale, { digits: 1 })}% acima</p>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Não identificado</p>
          )}
        </div>
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[10px] bg-background p-2.5">
      <dt className="text-[11px] text-subtle-foreground">{label}</dt>
      <dd className="num mt-0.5 text-xs font-semibold text-foreground">{value}</dd>
    </div>
  );
}

export function AssetAvatar({ item, size = 34 }: { item: Opportunity; size?: number }) {
  if (item.imageUrl) return <AssetIcon src={item.imageUrl} symbol={item.symbol} size={size} className="rounded-[10px]" />;
  return (
    <span aria-hidden style={{ width: size, height: size }} className="inline-flex shrink-0 items-center justify-center rounded-[10px] bg-surface-sunken text-[11px] font-semibold text-muted-foreground">
      {item.symbol.slice(0, 2)}
    </span>
  );
}

export function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function signed(n: number): string {
  return n > 0 ? `+${n}` : String(n);
}
