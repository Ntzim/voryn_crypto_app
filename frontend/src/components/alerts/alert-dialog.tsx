"use client";

import { LoaderCircle, TriangleAlert } from "lucide-react";
import { useId, useState, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";

import { AssetPicker } from "@/components/portfolio/asset-picker";
import { Alert as Callout, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { ApiError } from "@/lib/api/client";
import type { Alert, AlertInput, AlertType, AssetBrief, Timeframe } from "@/lib/api/types";
import { formatPrice, parseDecimalInput } from "@/lib/format";
import { usePreferences } from "@/lib/queries";
import { useAlertMutations } from "@/lib/signal-queries";

const TYPES: { value: AlertType; label: string; help: string }[] = [
  { value: "price_above", label: "Preço acima de", help: "Avisa quando o preço ultrapassa o valor." },
  { value: "price_below", label: "Preço abaixo de", help: "Avisa quando o preço cai abaixo do valor." },
  { value: "rsi_above", label: "RSI acima de", help: "RSI(14) do candle fechado acima do limite (ex.: 70, sobrecompra)." },
  { value: "rsi_below", label: "RSI abaixo de", help: "RSI(14) do candle fechado abaixo do limite (ex.: 30, sobrevenda)." },
  { value: "ma_cross", label: "Cruzamento de médias", help: "EMA rápida cruza a EMA lenta (ex.: 50/200)." },
  { value: "volume_spike", label: "Volume elevado", help: "Volume do candle fechado acima de N× a média de 20." },
  { value: "trend_change", label: "Mudança de tendência", help: "A classificação de tendência muda." },
  { value: "signal_change", label: "Mudança no sinal", help: "A classificação do sinal de oportunidade muda." },
  { value: "concentration", label: "Concentração da carteira", help: "Um ativo passa a pesar mais que o limite na sua carteira." },
];
const INDICATOR: AlertType[] = ["rsi_above", "rsi_below", "ma_cross", "volume_spike", "trend_change", "signal_change"];
const COOLDOWNS = [
  { value: 15, label: "15 minutos" },
  { value: 60, label: "1 hora" },
  { value: 360, label: "6 horas" },
  { value: 1440, label: "1 dia" },
  { value: 10080, label: "1 semana" },
];
const ANY = "__any__";

export function AlertDialog({ open, onOpenChange, alert }: { open: boolean; onOpenChange: (o: boolean) => void; alert: Alert | null }) {
  return <Dialog open={open} onOpenChange={onOpenChange}>{open && <Form alert={alert} onDone={() => onOpenChange(false)} />}</Dialog>;
}

function Form({ alert, onDone }: { alert: Alert | null; onDone: () => void }) {
  const { locale } = usePreferences();
  const normalize = (v: string) => parseDecimalInput(v, locale) ?? "";
  const p = alert?.params ?? {};
  const [type, setType] = useState<AlertType>(alert?.type ?? "price_above");
  const [asset, setAsset] = useState<AssetBrief | null>(alert?.asset ?? null);
  const [timeframe, setTimeframe] = useState<Timeframe>(alert?.timeframe ?? "1d");
  const [value, setValue] = useState<string>(String(p.target ?? p.level ?? p.ratio ?? p.threshold_pct ?? ""));
  const [currency, setCurrency] = useState<string>(String(p.currency ?? "USD"));
  const [fast, setFast] = useState<string>(String(p.fast ?? "50"));
  const [slow, setSlow] = useState<string>(String(p.slow ?? "200"));
  const [direction, setDirection] = useState<string>(String(p.direction ?? "any"));
  const [goal, setGoal] = useState<string>(String(p.to ?? ANY));
  const [cooldown, setCooldown] = useState<number>(alert?.cooldown_minutes ?? 360);
  const [email, setEmail] = useState<boolean>(alert?.notify_email ?? true);
  const { create, update } = useAlertMutations();
  const mutation = alert ? update : create;
  const error = mutation.error instanceof ApiError ? (mutation.error.fieldErrors[""] ?? mutation.error.message) : null;
  const meta = TYPES.find((t) => t.value === type)!;

  const params = (): Record<string, unknown> => {
    switch (type) {
      case "price_above":
      case "price_below":
        return { target: normalize(value), currency };
      case "rsi_above":
      case "rsi_below":
        return { level: normalize(value) };
      case "ma_cross":
        return { fast: Number(fast), slow: Number(slow), direction };
      case "volume_spike":
        return { ratio: normalize(value || "2") };
      case "trend_change":
      case "signal_change":
        return goal === ANY ? {} : { to: goal };
      case "concentration":
        return { threshold_pct: normalize(value) };
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const body: AlertInput = {
      type,
      asset_id: asset?.id ?? null,
      timeframe: INDICATOR.includes(type) ? timeframe : null,
      params: params(),
      notify_email: email,
      cooldown_minutes: cooldown,
      is_active: alert?.is_active ?? true,
    };
    const onSuccess = () => {
      toast.success(alert ? "Alerta atualizado." : "Alerta criado.");
      onDone();
    };
    if (alert) update.mutate({ id: alert.id, body }, { onSuccess });
    else create.mutate(body, { onSuccess });
  };

  return (
    <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-lg">
      <DialogHeader>
        <DialogTitle>{alert ? "Editar alerta" : "Novo alerta"}</DialogTitle>
        <DialogDescription>{meta.help}</DialogDescription>
      </DialogHeader>
      <form onSubmit={submit} className="space-y-4" noValidate>
        {error && (
          <Callout variant="destructive" className="border-destructive/30 bg-destructive/10">
            <TriangleAlert />
            <AlertDescription className="text-destructive">{error}</AlertDescription>
          </Callout>
        )}
        <Field label="Tipo">
          {(id) => (
            <Select value={type} onValueChange={(v) => setType(v as AlertType)}>
              <SelectTrigger id={id} className="h-11 w-full bg-surface"><SelectValue /></SelectTrigger>
              <SelectContent>{TYPES.map((t) => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}</SelectContent>
            </Select>
          )}
        </Field>
        <Field label={type === "concentration" ? "Ativo (opcional — vazio = qualquer ativo)" : "Ativo"}>
          {(id) => <AssetPicker id={id} value={asset} onChange={setAsset} />}
        </Field>

        {(type === "price_above" || type === "price_below") && (
          <div className="grid grid-cols-[1fr_120px] gap-3">
            <Field label="Preço-alvo">
              {(id) => (
                <>
                  <Input id={id} inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} className="num h-11 bg-surface" />
                  {value.trim() && (
                    <p className="num text-xs text-muted-foreground">
                      {parseDecimalInput(value, locale) ? `= ${formatPrice(parseDecimalInput(value, locale), currency === "BRL" ? "BRL" : "USD", locale)}` : "Número inválido"}
                    </p>
                  )}
                </>
              )}
            </Field>
            <Field label="Moeda">
              {(id) => (
                <Select value={currency} onValueChange={setCurrency}>
                  <SelectTrigger id={id} className="h-11 w-full bg-surface"><SelectValue /></SelectTrigger>
                  <SelectContent><SelectItem value="USD">USD</SelectItem><SelectItem value="BRL">BRL</SelectItem></SelectContent>
                </Select>
              )}
            </Field>
          </div>
        )}
        {(type === "rsi_above" || type === "rsi_below") && (
          <Field label="Nível do RSI (1–99)">{(id) => <Input id={id} inputMode="numeric" value={value} onChange={(e) => setValue(e.target.value)} placeholder={type === "rsi_above" ? "70" : "30"} className="num h-11 bg-surface" />}</Field>
        )}
        {type === "volume_spike" && (
          <Field label="Múltiplo da média de volume">{(id) => <Input id={id} inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} placeholder="2" className="num h-11 bg-surface" />}</Field>
        )}
        {type === "concentration" && (
          <Field label="Peso máximo na carteira (%)">{(id) => <Input id={id} inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} placeholder="50" className="num h-11 bg-surface" />}</Field>
        )}
        {type === "ma_cross" && (
          <div className="grid grid-cols-3 gap-3">
            {[["EMA rápida", fast, setFast], ["EMA lenta", slow, setSlow]].map(([label, v, set]) => (
              <Field key={label as string} label={label as string}>
                {(id) => (
                  <Select value={v as string} onValueChange={set as (x: string) => void}>
                    <SelectTrigger id={id} className="h-11 w-full bg-surface"><SelectValue /></SelectTrigger>
                    <SelectContent>{["9", "21", "50", "200"].map((n) => <SelectItem key={n} value={n}>{n}</SelectItem>)}</SelectContent>
                  </Select>
                )}
              </Field>
            ))}
            <Field label="Direção">
              {(id) => (
                <Select value={direction} onValueChange={setDirection}>
                  <SelectTrigger id={id} className="h-11 w-full bg-surface"><SelectValue /></SelectTrigger>
                  <SelectContent><SelectItem value="any">Ambas</SelectItem><SelectItem value="up">Alta</SelectItem><SelectItem value="down">Baixa</SelectItem></SelectContent>
                </Select>
              )}
            </Field>
          </div>
        )}
        {(type === "trend_change" || type === "signal_change") && (
          <Field label="Avisar quando mudar para">
            {(id) => (
              <Select value={goal} onValueChange={setGoal}>
                <SelectTrigger id={id} className="h-11 w-full bg-surface"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={ANY}>Qualquer mudança</SelectItem>
                  {(type === "trend_change"
                    ? [["uptrend", "Tendência de alta"], ["downtrend", "Tendência de baixa"], ["consolidation", "Consolidação"]]
                    : [["buy_potential", "Potencial de compra"], ["attention", "Atenção"], ["neutral", "Neutro"], ["sell_potential", "Potencial de venda"]]
                  ).map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}
                </SelectContent>
              </Select>
            )}
          </Field>
        )}
        {INDICATOR.includes(type) && (
          <Field label="Intervalo dos candles">
            {(id) => (
              <Select value={timeframe} onValueChange={(v) => setTimeframe(v as Timeframe)}>
                <SelectTrigger id={id} className="h-11 w-full bg-surface"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {(type === "signal_change" ? ["1d", "4h"] : ["15m", "1h", "4h", "1d", "1w"]).map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
                </SelectContent>
              </Select>
            )}
          </Field>
        )}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Intervalo mínimo entre avisos">
            {(id) => (
              <Select value={String(cooldown)} onValueChange={(v) => setCooldown(Number(v))}>
                <SelectTrigger id={id} className="h-11 w-full bg-surface"><SelectValue /></SelectTrigger>
                <SelectContent>{COOLDOWNS.map((c) => <SelectItem key={c.value} value={String(c.value)}>{c.label}</SelectItem>)}</SelectContent>
              </Select>
            )}
          </Field>
          <div className="flex items-end gap-2 pb-3">
            <Switch id="alert-email" checked={email} onCheckedChange={setEmail} />
            <Label htmlFor="alert-email">Também por e-mail</Label>
          </div>
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={onDone}>Cancelar</Button>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending && <LoaderCircle className="animate-spin" />}
            {alert ? "Salvar" : "Criar alerta"}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}

function Field({ label, children }: { label: string; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children(id)}
    </div>
  );
}
