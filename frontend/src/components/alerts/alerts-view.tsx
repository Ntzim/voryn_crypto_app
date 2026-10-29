"use client";

import { Bell, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/common/page-header";
import { EmptyState, ErrorState } from "@/components/common/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { isApiError } from "@/lib/api/client";
import type { Alert, AlertInput } from "@/lib/api/types";
import { formatRelative } from "@/lib/format";
import { usePreferences } from "@/lib/queries";
import { useAlertMutations, useAlerts, useNotificationMutations, useNotifications } from "@/lib/signal-queries";

import { AlertDialog } from "./alert-dialog";
import { NotificationItemRow } from "./notification-bell";

export function alertToInput(alert: Alert, changes: Partial<AlertInput> = {}): AlertInput {
  return {
    type: alert.type,
    asset_id: alert.asset?.id ?? null,
    timeframe: alert.timeframe,
    params: alert.params,
    notify_email: alert.notify_email,
    cooldown_minutes: alert.cooldown_minutes,
    is_active: alert.is_active,
    ...changes,
  };
}

export function AlertsView() {
  const { locale } = usePreferences();
  const alerts = useAlerts();
  const notifications = useNotifications(50);
  const { update, remove } = useAlertMutations();
  const { readAll } = useNotificationMutations();
  const [editing, setEditing] = useState<Alert | null>(null);
  const [open, setOpen] = useState(false);

  const toggle = (alert: Alert) =>
    update.mutate(
      { id: alert.id, body: alertToInput(alert, { is_active: !alert.is_active }) },
      { onError: (e) => toast.error(isApiError(e) ? e.message : "Não foi possível atualizar.") },
    );

  return (
    <>
      <PageHeader
        title="Alertas"
        description="Avisos quando preço, indicadores, tendência, sinal ou a concentração da carteira cruzam os limites definidos."
        actions={
          <Button onClick={() => { setEditing(null); setOpen(true); }}>
            <Plus /> Novo alerta
          </Button>
        }
      />
      <Tabs defaultValue="alertas">
        <TabsList className="mb-4">
          <TabsTrigger value="alertas">Meus alertas</TabsTrigger>
          <TabsTrigger value="notificacoes">
            Notificações {notifications.data?.unread ? <Badge className="ml-1.5 h-4 px-1.5 text-[10px]">{notifications.data.unread}</Badge> : null}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="alertas">
          <Card className="gap-0 py-0">
            {alerts.isError ? (
              <ErrorState error={alerts.error} onRetry={() => alerts.refetch()} />
            ) : !alerts.data ? (
              <div className="space-y-3 p-4">{Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-12" />)}</div>
            ) : alerts.data.length === 0 ? (
              <EmptyState
                icon={Bell}
                title="Nenhum alerta configurado"
                description="Crie alertas de preço, RSI, cruzamento de médias, volume, tendência, sinal ou concentração."
                action={<Button onClick={() => setOpen(true)}><Plus /> Criar alerta</Button>}
              />
            ) : (
              <ul className="divide-y divide-border">
                {alerts.data.map((alert) => (
                  <li key={alert.id} className="flex items-center gap-3 px-4 py-3 md:px-5">
                    <Switch checked={alert.is_active} onCheckedChange={() => toggle(alert)} aria-label={alert.is_active ? "Desativar alerta" : "Ativar alerta"} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-foreground">{alert.description}</p>
                      <p className="text-xs text-muted-foreground">
                        {alert.last_triggered_at ? `Disparou ${formatRelative(alert.last_triggered_at, locale)} · ${alert.trigger_count}×` : "Ainda não disparou"}
                        {" · "}cooldown {alert.cooldown_minutes >= 60 ? `${alert.cooldown_minutes / 60} h` : `${alert.cooldown_minutes} min`}
                        {alert.notify_email && " · e-mail"}
                      </p>
                    </div>
                    <Button variant="ghost" size="icon-sm" aria-label="Editar alerta" onClick={() => { setEditing(alert); setOpen(true); }}>
                      <Pencil />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Excluir alerta"
                      onClick={() => remove.mutate(alert.id, { onSuccess: () => toast.success("Alerta excluído.") })}
                    >
                      <Trash2 />
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <p className="mt-3 text-xs text-subtle-foreground">
            Alertas são avaliados a cada 5 minutos e disparam quando a condição passa a ser verdadeira — não repetidamente
            enquanto ela se mantém. Nunca usamos cotações desatualizadas. Limites: 30 notificações e 10 e-mails por hora.
          </p>
        </TabsContent>

        <TabsContent value="notificacoes">
          <Card className="gap-0 p-2">
            {notifications.data?.unread ? (
              <div className="flex justify-end px-2 pt-1">
                <Button variant="ghost" size="sm" onClick={() => readAll.mutate()}>Marcar todas como lidas</Button>
              </div>
            ) : null}
            {notifications.data?.items.length ? (
              <ul>
                {notifications.data.items.map((n) => (
                  <li key={n.id}><NotificationItemRow item={n} /></li>
                ))}
              </ul>
            ) : (
              <EmptyState icon={Bell} title="Nenhuma notificação" description="Quando um alerta disparar, ele aparece aqui e no sino do topo." />
            )}
          </Card>
        </TabsContent>
      </Tabs>
      <AlertDialog open={open} onOpenChange={setOpen} alert={editing} />
    </>
  );
}
