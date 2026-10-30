"use client";

import { cn } from "cn";
import { ArrowRight, ChevronLeft, ChevronRight, Pencil, ReceiptText, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { AssetIcon } from "@/components/common/asset-icon";
import { EmptyState, ErrorState } from "@/components/common/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { isApiError } from "@/lib/api/client";
import type { Transaction, TxType } from "@/lib/api/types";
import { formatDateTime, formatMoney, formatNumber, formatPrice } from "@/lib/format";
import { TX_LABELS, useTransactionMutations, useTransactions } from "@/lib/portfolio-queries";
import { usePreferences } from "@/lib/queries";

const PAGE_SIZE = 25;
const ALL = "all";
const TYPE_TONE: Record<TxType, string> = {
  buy: "text-success",
  deposit: "text-success",
  sell: "text-destructive",
  withdrawal: "text-destructive",
  transfer: "text-muted-foreground",
  conversion: "text-violet",
  fee: "text-warning",
};

export function TransactionsList({
  portfolioId,
  onEdit,
}: {
  portfolioId: string;
  onEdit: (tx: Transaction) => void;
}) {
  const { locale, timeZone } = usePreferences();
  const [type, setType] = useState<TxType | undefined>();
  const [page, setPage] = useState(1);
  const [deleting, setDeleting] = useState<Transaction | null>(null);
  const query = useTransactions(portfolioId, { type, page, pageSize: PAGE_SIZE });
  const { remove } = useTransactionMutations(portfolioId);
  const totalPages = query.data ? Math.max(1, Math.ceil(query.data.total / PAGE_SIZE)) : 1;

  const confirmDelete = () => {
    if (!deleting) return;
    remove.mutate(deleting.id, {
      onSuccess: () => {
        toast.success("Transação excluída.");
        setDeleting(null);
      },
      onError: (error) => {
        toast.error(isApiError(error) ? error.message : "Não foi possível excluir.");
        setDeleting(null);
      },
    });
  };

  return (
    <div>
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3 md:px-5">
        <Select
          value={type ?? ALL}
          onValueChange={(v) => {
            setType(v === ALL ? undefined : (v as TxType));
            setPage(1);
          }}
        >
          <SelectTrigger className="h-9 w-44 bg-surface" aria-label="Filtrar por tipo"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Todos os tipos</SelectItem>
            {(Object.keys(TX_LABELS) as TxType[]).map((t) => (
              <SelectItem key={t} value={t}>{TX_LABELS[t]}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {query.data && <span className="text-xs text-muted-foreground">{query.data.total} transação(ões)</span>}
      </div>

      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      ) : !query.data ? (
        <div className="space-y-3 p-4">
          {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-12 w-full" />)}
        </div>
      ) : query.data.items.length === 0 ? (
        <EmptyState icon={ReceiptText} title="Nenhuma transação" description={type ? "Nenhuma transação deste tipo." : "Registre uma transação ou importe um CSV."} />
      ) : (
        <ul className={cn("divide-y divide-border transition-opacity", query.isPlaceholderData && "opacity-60")}>
          {query.data.items.map((tx) => (
            <li key={tx.id} className="group flex items-center gap-3 px-4 py-3 md:px-5">
              <AssetIcon src={tx.asset.image_url} symbol={tx.asset.symbol} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                  <span className={cn("text-sm font-medium", TYPE_TONE[tx.type])}>{TX_LABELS[tx.type]}</span>
                  <span className="num text-sm text-foreground">
                    {formatNumber(tx.quantity, locale, { digits: 8 })} {tx.asset.symbol}
                  </span>
                  {tx.to_asset && (
                    <span className="num inline-flex items-center gap-1 text-sm text-foreground">
                      <ArrowRight className="size-3.5 text-subtle-foreground" />
                      {formatNumber(tx.to_quantity, locale, { digits: 8 })} {tx.to_asset.symbol}
                    </span>
                  )}
                  {tx.source === "csv" && <Badge variant="outline" className="text-[10px] text-muted-foreground">CSV</Badge>}
                </div>
                <p className="truncate text-xs text-muted-foreground">
                  {formatDateTime(tx.executed_at, locale, timeZone)}
                  {tx.unit_price && ` · ${formatPrice(tx.unit_price, tx.quote_currency, locale)}/un.`}
                  {tx.exchange_id && ` · ${tx.exchange_id}${tx.to_exchange_id ? ` → ${tx.to_exchange_id}` : ""}`}
                  {tx.notes && ` · ${tx.notes}`}
                </p>
              </div>
              {tx.gross_amount && (
                <span className="num hidden text-right text-sm font-medium text-foreground sm:block">
                  {formatMoney(tx.gross_amount, tx.quote_currency, locale)}
                </span>
              )}
              <div className="flex shrink-0 gap-1 md:opacity-0 md:transition-opacity md:group-focus-within:opacity-100 md:group-hover:opacity-100">
                <Button variant="ghost" size="icon-sm" aria-label="Editar transação" onClick={() => onEdit(tx)}>
                  <Pencil />
                </Button>
                <Button variant="ghost" size="icon-sm" aria-label="Excluir transação" onClick={() => setDeleting(tx)}>
                  <Trash2 />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-end gap-2 border-t border-border px-4 py-3">
          <span className="num text-xs text-muted-foreground">Página {page} de {totalPages}</span>
          <Button variant="outline" size="icon-sm" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Página anterior"><ChevronLeft /></Button>
          <Button variant="outline" size="icon-sm" disabled={page >= totalPages} onClick={() => setPage(page + 1)} aria-label="Próxima página"><ChevronRight /></Button>
        </div>
      )}

      <Dialog open={deleting !== null} onOpenChange={(o) => !o && setDeleting(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Excluir transação?</DialogTitle>
            <DialogDescription>
              {deleting && `${TX_LABELS[deleting.type]} de ${formatNumber(deleting.quantity, locale, { digits: 8 })} ${deleting.asset.symbol} em ${formatDateTime(deleting.executed_at, locale, timeZone)}.`}{" "}
              Posições e rentabilidade serão recalculadas. A exclusão é bloqueada se tornar alguma venda posterior impossível.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleting(null)}>Cancelar</Button>
            <Button variant="destructive" onClick={confirmDelete} disabled={remove.isPending}>Excluir</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
