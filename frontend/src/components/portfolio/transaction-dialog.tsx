"use client";

import { cn } from "cn";
import { LoaderCircle, TriangleAlert } from "lucide-react";
import { useId, useState, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ApiError } from "@/lib/api/client";
import type { AssetBrief, Currency, Transaction, TransactionInput, TxType } from "@/lib/api/types";
import { formatMoney, parseDecimalInput } from "@/lib/format";
import { TX_LABELS, useExchanges, useTransactionMutations } from "@/lib/portfolio-queries";
import { usePreferences } from "@/lib/queries";

import { AssetPicker } from "./asset-picker";

const TYPES: TxType[] = ["buy", "sell", "deposit", "withdrawal", "transfer", "conversion", "fee"];

const HELP: Record<TxType, string> = {
  buy: "Compra paga com moeda fiduciária. Conta como aporte.",
  sell: "Venda por moeda fiduciária. Realiza lucro ou prejuízo e conta como retirada.",
  deposit: "Entrada de cripto vinda de fora (outra carteira não acompanhada, presente, airdrop). Conta como aporte pelo valor informado.",
  withdrawal: "Saída de cripto para fora da Voryn. Conta como retirada; não realiza resultado.",
  transfer: "Movimento entre suas próprias contas. Não é aporte nem lucro; só a taxa de rede reduz o saldo.",
  conversion: "Troca de um cripto por outro (ex.: USDT → BTC). Realiza o resultado do ativo de origem.",
  fee: "Taxa paga no próprio ativo (ex.: staking, custódia). Reduz o saldo e é registrada como despesa.",
};

const PRICED: TxType[] = ["buy", "sell", "deposit", "conversion"];

function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

type Form = {
  type: TxType;
  asset: AssetBrief | null;
  quantity: string;
  unitPrice: string;
  currency: Currency;
  fee: string;
  feeQuantity: string;
  toAsset: AssetBrief | null;
  toQuantity: string;
  executedAt: string;
  exchange: string;
  toExchange: string;
  notes: string;
};

function initialForm(tx: Transaction | null, currency: Currency): Form {
  const decimal = (v: string | null | undefined) => (v && Number(v) !== 0 ? String(Number(v)) : "");
  if (!tx) {
    return {
      type: "buy", asset: null, quantity: "", unitPrice: "", currency, fee: "", feeQuantity: "",
      toAsset: null, toQuantity: "", executedAt: toLocalInput(new Date().toISOString()),
      exchange: "", toExchange: "", notes: "",
    };
  }
  return {
    type: tx.type,
    asset: tx.asset,
    quantity: decimal(tx.quantity),
    unitPrice: decimal(tx.unit_price),
    currency: tx.quote_currency,
    fee: decimal(tx.fee_amount),
    feeQuantity: decimal(tx.fee_quantity),
    toAsset: tx.to_asset ?? null,
    toQuantity: decimal(tx.to_quantity),
    executedAt: toLocalInput(tx.executed_at),
    exchange: tx.exchange_id ?? "",
    toExchange: tx.to_exchange_id ?? "",
    notes: tx.notes ?? "",
  };
}

export function TransactionDialog({
  open,
  onOpenChange,
  portfolioId,
  transaction,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  portfolioId: string;
  transaction: Transaction | null;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {open && (
        <TransactionForm portfolioId={portfolioId} transaction={transaction} onDone={() => onOpenChange(false)} />
      )}
    </Dialog>
  );
}

function TransactionForm({
  portfolioId,
  transaction,
  onDone,
}: {
  portfolioId: string;
  transaction: Transaction | null;
  onDone: () => void;
}) {
  const { currency, locale } = usePreferences();
  const [form, setForm] = useState<Form>(() => initialForm(transaction, currency));
  const [localError, setLocalError] = useState<string | null>(null);
  const { create, update } = useTransactionMutations(portfolioId);
  const exchanges = useExchanges();
  const mutation = transaction ? update : create;
  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => ({ ...f, [key]: value }));

  const errors = mutation.error instanceof ApiError ? mutation.error.fieldErrors : {};
  const apiError =
    mutation.error instanceof ApiError
      ? mutation.error.code === "validation_error"
        ? errors[""] ?? null
        : mutation.error.message
      : mutation.error
        ? "Não foi possível salvar."
        : null;

  const priced = PRICED.includes(form.type);
  const showPrice = priced || form.type === "withdrawal";
  const showFee = ["buy", "sell", "deposit", "withdrawal", "conversion"].includes(form.type);
  const showFeeQuantity = ["buy", "transfer", "withdrawal"].includes(form.type);
  const num = (v: string) => parseDecimalInput(v, locale);
  const qty = Number(num(form.quantity) ?? 0);
  const price = Number(num(form.unitPrice) ?? 0);
  // Display-only preview; the server computes and stores the authoritative amount.
  const preview = showPrice && qty > 0 && price > 0 ? qty * price : null;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setLocalError(null);
    if (!form.asset) return setLocalError("Selecione o ativo.");
    if (form.type === "conversion" && !form.toAsset) return setLocalError("Selecione o ativo recebido.");
    const executed = new Date(form.executedAt);
    if (Number.isNaN(executed.getTime())) return setLocalError("Informe a data e o horário.");
    const fields: [string, string][] = [
      ["Quantidade", form.quantity],
      ["Preço", form.unitPrice],
      ["Taxa", form.fee],
      ["Taxa no ativo", form.feeQuantity],
      ["Quantidade recebida", form.toQuantity],
    ];
    const invalid = fields.find(([, v]) => v.trim() && num(v) === null);
    if (invalid) return setLocalError(`Número inválido em “${invalid[0]}”.`);
    const opt = (v: string) => (v.trim() ? num(v) : null);
    const body: TransactionInput = {
      type: form.type,
      asset_id: form.asset.id,
      quantity: num(form.quantity) ?? "",
      unit_price: showPrice ? opt(form.unitPrice) : null,
      quote_currency: form.currency,
      fee_amount: showFee ? (opt(form.fee) ?? "0") : "0",
      fee_quantity: showFeeQuantity ? (opt(form.feeQuantity) ?? "0") : "0",
      to_asset_id: form.type === "conversion" ? form.toAsset?.id : null,
      to_quantity: form.type === "conversion" ? opt(form.toQuantity) : null,
      executed_at: executed.toISOString(),
      exchange_id: form.exchange || null,
      to_exchange_id: form.type === "transfer" ? form.toExchange || null : null,
      notes: form.notes.trim() || null,
    };
    const onSuccess = () => {
      toast.success(transaction ? "Transação atualizada." : "Transação registrada.");
      onDone();
    };
    if (transaction) update.mutate({ id: transaction.id, body }, { onSuccess });
    else create.mutate(body, { onSuccess });
  };

  return (
    <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-xl">
      <DialogHeader>
        <DialogTitle>{transaction ? "Editar transação" : "Nova transação"}</DialogTitle>
        <DialogDescription>{HELP[form.type]}</DialogDescription>
      </DialogHeader>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <div role="radiogroup" aria-label="Tipo de transação" className="flex flex-wrap gap-1.5">
          {TYPES.map((t) => (
            <button
              key={t}
              type="button"
              role="radio"
              aria-checked={form.type === t}
              onClick={() => set("type", t)}
              className={cn(
                "h-8 rounded-md border px-3 text-xs font-medium transition-colors",
                form.type === t
                  ? "border-primary/60 bg-primary/15 text-foreground"
                  : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {TX_LABELS[t]}
            </button>
          ))}
        </div>

        {(localError || apiError) && (
          <Alert variant="destructive" className="border-destructive/30 bg-destructive/10">
            <TriangleAlert />
            <AlertDescription className="text-destructive">{localError ?? apiError}</AlertDescription>
          </Alert>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={form.type === "conversion" ? "Ativo de origem" : "Ativo"} error={errors.asset_id} className="sm:col-span-2">
            {(id) => <AssetPicker id={id} value={form.asset} onChange={(a) => set("asset", a)} />}
          </Field>
          <Field label={form.type === "conversion" ? "Quantidade entregue" : "Quantidade"} error={errors.quantity}>
            {(id) => <NumberInput id={id} value={form.quantity} onChange={(v) => set("quantity", v)} />}
          </Field>
          <Field label="Data e horário" error={errors.executed_at}>
            {(id) => (
              <Input id={id} type="datetime-local" value={form.executedAt} onChange={(e) => set("executedAt", e.target.value)} className="h-11 bg-surface" />
            )}
          </Field>

          {showPrice && (
            <>
              <Field
                label={form.type === "withdrawal" ? "Valor de referência por unidade (opcional)" : form.type === "conversion" ? "Valor por unidade entregue" : "Preço unitário"}
                error={errors.unit_price}
              >
                {(id) => <NumberInput id={id} value={form.unitPrice} onChange={(v) => set("unitPrice", v)} />}
              </Field>
              <Field label="Moeda">
                {(id) => (
                  <Select value={form.currency} onValueChange={(v) => set("currency", v as Currency)}>
                    <SelectTrigger id={id} className="h-11 w-full bg-surface"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="BRL">BRL — Real</SelectItem>
                      <SelectItem value="USD">USD — Dólar</SelectItem>
                    </SelectContent>
                  </Select>
                )}
              </Field>
            </>
          )}

          {form.type === "conversion" && (
            <>
              <Field label="Ativo recebido" error={errors.to_asset_id}>
                {(id) => <AssetPicker id={id} value={form.toAsset} onChange={(a) => set("toAsset", a)} />}
              </Field>
              <Field label="Quantidade recebida" error={errors.to_quantity}>
                {(id) => <NumberInput id={id} value={form.toQuantity} onChange={(v) => set("toQuantity", v)} />}
              </Field>
            </>
          )}

          {showFee && (
            <Field label={`Taxa em ${form.currency} (opcional)`} error={errors.fee_amount}>
              {(id) => <NumberInput id={id} value={form.fee} onChange={(v) => set("fee", v)} />}
            </Field>
          )}
          {showFeeQuantity && (
            <Field
              label={`Taxa em ${form.asset?.symbol ?? "unidades do ativo"} (opcional)`}
              error={errors.fee_quantity}
              hint={form.type === "buy" ? "Quando a exchange desconta a taxa do ativo recebido." : "Taxa de rede descontada do saldo."}
            >
              {(id) => <NumberInput id={id} value={form.feeQuantity} onChange={(v) => set("feeQuantity", v)} />}
            </Field>
          )}

          <Field label={form.type === "transfer" ? "Origem" : "Exchange ou carteira (opcional)"}>
            {(id) => (
              <ExchangeSelect id={id} value={form.exchange} onChange={(v) => set("exchange", v)} options={exchanges.data} />
            )}
          </Field>
          {form.type === "transfer" && (
            <Field label="Destino">
              {(id) => (
                <ExchangeSelect id={id} value={form.toExchange} onChange={(v) => set("toExchange", v)} options={exchanges.data} />
              )}
            </Field>
          )}

          <Field label="Observações (opcional)" className="sm:col-span-2" error={errors.notes}>
            {(id) => (
              <Input id={id} value={form.notes} onChange={(e) => set("notes", e.target.value)} maxLength={1000} className="h-11 bg-surface" />
            )}
          </Field>
        </div>

        {preview !== null && (
          <p className="num rounded-lg bg-surface px-3 py-2 text-sm text-muted-foreground">
            Total {form.type === "conversion" ? "entregue" : "da operação"}:{" "}
            <span className="font-medium text-foreground">{formatMoney(preview, form.currency, locale)}</span>
            {showFee && Number(num(form.fee) ?? 0) > 0 && " + taxa"}
          </p>
        )}

        <DialogFooter>
          <Button type="button" variant="ghost" onClick={onDone}>Cancelar</Button>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending && <LoaderCircle className="animate-spin" />}
            {transaction ? "Salvar alterações" : "Registrar"}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}

function Field({
  label,
  error,
  hint,
  className,
  children,
}: {
  label: string;
  error?: string;
  hint?: string;
  className?: string;
  children: (id: string) => ReactNode;
}) {
  const id = useId();
  return (
    <div className={cn("space-y-1.5", className)}>
      <Label htmlFor={id}>{label}</Label>
      {children(id)}
      {error ? <p className="text-xs text-destructive">{error}</p> : hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function NumberInput({ id, value, onChange }: { id: string; value: string; onChange: (v: string) => void }) {
  return (
    <Input
      id={id}
      inputMode="decimal"
      autoComplete="off"
      value={value}
      onChange={(e) => onChange(e.target.value.replace(/[^\d.,]/g, ""))}
      className="num h-11 bg-surface"
      placeholder="0,00"
    />
  );
}

const NONE = "__none__";

function ExchangeSelect({
  id,
  value,
  onChange,
  options,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  options: { id: string; name: string }[] | undefined;
}) {
  return (
    <Select value={value || NONE} onValueChange={(v) => onChange(v === NONE ? "" : v)}>
      <SelectTrigger id={id} className="h-11 w-full bg-surface"><SelectValue /></SelectTrigger>
      <SelectContent>
        <SelectItem value={NONE}>Não informar</SelectItem>
        {options?.map((e) => (
          <SelectItem key={e.id} value={e.id}>{e.name}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
