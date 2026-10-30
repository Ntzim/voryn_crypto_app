"use client";

import { cn } from "cn";
import { Loader2, Lock, Plug, RefreshCw, Unplug } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { EmptyState } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/client";
import type { ExchangeConnection, Locale } from "@/lib/api/types";
import { useExchangeConnections, useExchangeMutations, useExchangeRecords } from "@/lib/exchange-queries";
import { formatDateTime, formatNumber, formatRelative } from "@/lib/format";
import { usePreferences } from "@/lib/queries";

import { SettingsSection } from "./section";

const STATUS = {
  active: { label: "Ativa", className: "text-success bg-success/10 border-success/30" },
  error: { label: "Erro na última sincronização", className: "text-warning bg-warning/10 border-warning/30" },
  blocked: { label: "Bloqueada", className: "text-destructive bg-destructive/10 border-destructive/30" },
} as const;

/** After connecting or asking for a sync, poll for this long while the worker runs. */
const POLL_FOR_MS = 90_000;

export function IntegrationsSection() {
  const [polling, setPolling] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const connections = useExchangeConnections(polling ? 3000 : false);
  const [open, setOpen] = useState(false);
  const startPolling = () => {
    setPolling(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setPolling(false), POLL_FOR_MS);
  };
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  return (
    <SettingsSection
      title="Exchanges"
      description={
        <>
          Sincronize operações, depósitos e saques da Binance com sua carteira.
          <span className="mt-2 flex items-start gap-1.5 text-xs text-subtle-foreground">
            <Lock className="mt-0.5 size-3.5 shrink-0" /> Somente chaves de leitura, cifradas no servidor. Chaves com permissão
            de negociação ou saque são recusadas.
          </span>
        </>
      }
    >
      {connections.isPending ? (
        <Skeleton className="h-32 w-full" />
      ) : (
        <div className="flex flex-col gap-4">
          {connections.data?.length ? (
            connections.data.map((c) => <ConnectionCard key={c.id} connection={c} polling={polling} onSynced={startPolling} />)
          ) : (
            <EmptyState
              icon={Plug}
              title="Nenhuma exchange conectada"
              description="Conecte uma chave somente leitura da Binance. A Coinbase e a Kraken virão depois."
              className="items-start px-0 py-6 text-left sm:items-center sm:text-center"
            />
          )}
          <div>
            <Button variant="outline" onClick={() => setOpen(true)}>
              <Plug /> Conectar Binance
            </Button>
          </div>
        </div>
      )}
      <ConnectDialog
        open={open}
        onOpenChange={setOpen}
        onConnected={() => {
          setOpen(false);
          startPolling();
        }}
      />
    </SettingsSection>
  );
}

function ConnectionCard({
  connection: c,
  polling,
  onSynced,
}: {
  connection: ExchangeConnection;
  polling: boolean;
  onSynced: () => void;
}) {
  const { locale, timeZone } = usePreferences();
  const { sync, remove } = useExchangeMutations();
  const [confirm, setConfirm] = useState(false);
  const [showReview, setShowReview] = useState(false);
  const records = useExchangeRecords(c.id, showReview);
  const status = STATUS[c.status];
  const waiting = polling && !c.last_synced_at;
  const syncError = sync.error instanceof ApiError ? sync.error.message : null;

  return (
    <div className="rounded-xl border border-border bg-surface/60 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-medium text-foreground">
            {c.exchange_name} · {c.label}
          </p>
          <p className="text-xs text-muted-foreground">
            Chave …{c.key_hint} ·{" "}
            {c.last_synced_at ? `sincronizada ${formatRelative(c.last_synced_at, locale)}` : waiting ? "primeira sincronização em andamento" : "ainda não sincronizada"}
          </p>
        </div>
        <span className={cn("rounded-full border px-2 py-0.5 text-xs", status.className)}>{status.label}</span>
      </div>
      {c.last_error && <p className="mt-2 text-sm text-destructive">{c.last_error}</p>}

      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm">
        <span>
          <span className="num font-medium text-foreground">{c.imported}</span> <span className="text-muted-foreground">registros importados</span>
        </span>
        {c.needs_review > 0 && (
          <button type="button" onClick={() => setShowReview((v) => !v)} className="text-warning underline-offset-2 hover:underline">
            <span className="num font-medium">{c.needs_review}</span> para revisar
          </button>
        )}
      </div>

      {showReview && (
        <div className="mt-3 rounded-lg border border-border bg-card p-3">
          <p className="mb-2 text-xs text-muted-foreground">
            Não importados para não inventar dados. Registre manualmente o que falta (por exemplo, a compra original de um ativo
            transferido) e sincronize de novo.
          </p>
          {records.isPending ? (
            <Skeleton className="h-16 w-full" />
          ) : (
            <ul className="max-h-60 space-y-2 overflow-y-auto text-sm">
              {records.data?.map((r) => (
                <li key={r.id} className="border-b border-border pb-2 last:border-0">
                  <p className="text-foreground">
                    {r.summary} <span className="text-xs text-muted-foreground">· {formatDateTime(r.occurred_at, locale, timeZone)}</span>
                  </p>
                  {r.reason && <p className="text-xs text-warning">{r.reason}</p>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {c.reconciliation && <Reconciliation connection={c} locale={locale} />}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={sync.isPending || c.status === "blocked"}
          onClick={() => sync.mutate(c.id, { onSuccess: onSynced })}
        >
          {sync.isPending || waiting ? <Loader2 className="animate-spin" /> : <RefreshCw />} Sincronizar agora
        </Button>
        <Button size="sm" variant="ghost" className="text-muted-foreground" onClick={() => setConfirm(true)}>
          <Unplug /> Desconectar
        </Button>
        {syncError && <span className="text-xs text-warning">{syncError}</span>}
      </div>

      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Desconectar {c.exchange_name}?</DialogTitle>
            <DialogDescription>
              A chave e os registros sincronizados serão apagados. As transações já importadas continuam na sua carteira.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirm(false)}>
              Cancelar
            </Button>
            <Button variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate(c.id, { onSuccess: () => setConfirm(false) })}>
              Desconectar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Reconciliation({ connection: c, locale }: { connection: ExchangeConnection; locale: Locale }) {
  const rec = c.reconciliation;
  if (!rec || rec.assets.length === 0) return null;
  const qty = (v: string) => formatNumber(v, locale, { digits: 8 });
  return (
    <details className="mt-3 rounded-lg border border-border bg-card px-3 py-2" open={!rec.ok}>
      <summary className="cursor-pointer text-sm">
        Conciliação de saldos:{" "}
        <span className={rec.ok ? "text-success" : "text-warning"}>{rec.ok ? "tudo confere" : "há diferenças"}</span>
      </summary>
      <div className="mt-2 overflow-x-auto">
        <table className="num w-full min-w-[440px] text-xs">
          <thead className="text-muted-foreground">
            <tr className="border-b border-border">
              <th className="py-1.5 text-left font-medium">Ativo</th>
              <th className="py-1.5 text-right font-medium">Na exchange</th>
              <th className="py-1.5 text-right font-medium">Na Voryn</th>
              <th className="py-1.5 text-right font-medium">Diferença</th>
            </tr>
          </thead>
          <tbody>
            {rec.assets.map((a) => (
              <tr key={a.symbol} className="border-b border-border last:border-0">
                <td className="py-1.5 font-medium text-foreground">{a.symbol}</td>
                <td className="py-1.5 text-right">{qty(a.exchange)}</td>
                <td className="py-1.5 text-right">{qty(a.voryn)}</td>
                <td className={cn("py-1.5 text-right", a.status === "ok" ? "text-success" : "text-warning")}>
                  {a.status === "ok" ? "ok" : qty(a.difference)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-subtle-foreground">
        Compara o saldo atual da exchange com as transações da Voryn atribuídas a ela. Diferenças vêm de produtos não lidos (Convert,
        Earn, P2P), registros em revisão ou movimentações anteriores ao período sincronizado.
      </p>
    </details>
  );
}

function ConnectDialog({
  open,
  onOpenChange,
  onConnected,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConnected: () => void;
}) {
  const { connect } = useExchangeMutations();
  const [label, setLabel] = useState("Binance");
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const error = connect.error instanceof ApiError ? connect.error.message : connect.error ? "Não foi possível conectar." : null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    connect.mutate(
      { exchange_id: "binance", label, api_key: key, api_secret: secret },
      {
        onSuccess: () => {
          setKey("");
          setSecret("");
          onConnected();
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Conectar Binance</DialogTitle>
          <DialogDescription>Use uma chave de API criada só para a Voryn, com permissão apenas de leitura.</DialogDescription>
        </DialogHeader>
        <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
          <li>Na Binance, abra Conta → Gerenciamento de API e crie uma chave do tipo gerada pelo sistema.</li>
          <li>
            Deixe marcada <strong className="text-foreground">somente</strong> a opção “Habilitar leitura”. Não habilite negociação, saque
            ou transferências.
          </li>
          <li>Copie a chave e o segredo abaixo. O segredo não é exibido de novo pela Binance nem pela Voryn.</li>
        </ol>
        <form onSubmit={submit} className="flex flex-col gap-3" autoComplete="off">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="ex-label">Nome</Label>
            <Input id="ex-label" value={label} maxLength={80} onChange={(e) => setLabel(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="ex-key">Chave de API</Label>
            <Input id="ex-key" value={key} onChange={(e) => setKey(e.target.value)} spellCheck={false} autoComplete="off" />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="ex-secret">Segredo</Label>
            <Input id="ex-secret" type="password" value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="new-password" />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={connect.isPending || key.length < 16 || secret.length < 16}>
              {connect.isPending && <Loader2 className="animate-spin" />} Validar e conectar
            </Button>
          </DialogFooter>
        </form>
        <p className="text-xs text-subtle-foreground">
          A chave é verificada na Binance antes de ser salva. A importação cobre negociações spot contra BRL, USDT, USDC e FDUSD,
          depósitos e saques de cripto do último ano.
        </p>
      </DialogContent>
    </Dialog>
  );
}
