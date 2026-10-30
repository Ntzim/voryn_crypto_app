"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Monitor, ShieldCheck, Smartphone } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Field, FormError, PasswordStrength, fieldErrors } from "@/components/auth/form-parts";
import { ErrorState } from "@/components/common/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, isApiError } from "@/lib/api/client";
import type { Message } from "@/lib/api/types";
import { formatDateTime, formatRelative } from "@/lib/format";
import { queryKeys, useMe, usePreferences, useSessions } from "@/lib/queries";
import { describeUserAgent } from "@/lib/user-agent";

import { SettingsSection } from "./section";
import { TwoFactorDisableDialog, TwoFactorSetupDialog } from "./two-factor-dialogs";

export function SecuritySection() {
  return (
    <div className="space-y-4">
      <ChangePassword />
      <TwoFactor />
      <Sessions />
    </div>
  );
}

function ChangePassword() {
  const queryClient = useQueryClient();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const change = useMutation({
    mutationFn: () =>
      api<void>("/me/password", { method: "POST", body: { current_password: current, new_password: next } }),
    onSuccess: () => {
      setCurrent("");
      setNext("");
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions });
      toast.success("Senha alterada. As demais sessões foram encerradas.");
    },
  });
  const errors = fieldErrors(change.error);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    change.mutate();
  };

  return (
    <SettingsSection title="Senha" description="Ao alterar a senha, todas as outras sessões são encerradas.">
      <form onSubmit={submit} className="max-w-md space-y-5" noValidate>
        <FormError error={change.error} />
        <Field label="Senha atual" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} error={errors.current_password} />
        <Field
          label="Nova senha"
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          error={errors.new_password}
          hint={<PasswordStrength password={next} />}
          maxLength={128}
        />
        <Button type="submit" disabled={change.isPending || !current || !next}>
          Alterar senha
        </Button>
      </form>
    </SettingsSection>
  );
}

function TwoFactor() {
  const { data: user } = useMe();
  const [setupOpen, setSetupOpen] = useState(false);
  const [disableOpen, setDisableOpen] = useState(false);
  if (!user) return <Skeleton className="h-32 rounded-xl" />;

  return (
    <SettingsSection
      title="Autenticação em dois fatores"
      description="Exige um código do seu aplicativo autenticador (Google Authenticator, 1Password, Authy) a cada login."
    >
      <div className="flex flex-col gap-4 rounded-lg border border-border bg-surface p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <ShieldCheck className={user.mfa_enabled ? "size-5 text-success" : "size-5 text-subtle-foreground"} />
          <div>
            <p className="text-sm font-medium text-foreground">{user.mfa_enabled ? "Ativada" : "Desativada"}</p>
            <p className="text-xs text-muted-foreground">
              {user.mfa_enabled
                ? "Sua conta exige o segundo fator no login."
                : "Recomendamos ativar para proteger sua conta."}
            </p>
          </div>
        </div>
        {user.mfa_enabled ? (
          <Button variant="outline" onClick={() => setDisableOpen(true)}>
            Desativar
          </Button>
        ) : (
          <Button onClick={() => setSetupOpen(true)}>Ativar 2FA</Button>
        )}
      </div>
      <TwoFactorSetupDialog open={setupOpen} onOpenChange={setSetupOpen} />
      <TwoFactorDisableDialog open={disableOpen} onOpenChange={setDisableOpen} />
    </SettingsSection>
  );
}

function Sessions() {
  const sessions = useSessions();
  const { locale, timeZone } = usePreferences();
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: queryKeys.sessions });

  const revoke = useMutation({
    mutationFn: (id: string) => api<void>(`/me/sessions/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      void refresh();
      toast.success("Sessão encerrada.");
    },
    onError: (error) => toast.error(isApiError(error) ? error.message : "Não foi possível encerrar a sessão."),
  });
  const revokeOthers = useMutation({
    mutationFn: () => api<Message>("/me/sessions/revoke-others", { method: "POST" }),
    onSuccess: (data) => {
      void refresh();
      toast.success(data.message);
    },
  });

  const others = sessions.data?.filter((s) => !s.current).length ?? 0;

  return (
    <SettingsSection title="Sessões ativas" description="Dispositivos conectados à sua conta. Encerre qualquer sessão que você não reconheça.">
      {sessions.isError ? (
        <ErrorState error={sessions.error} onRetry={() => sessions.refetch()} />
      ) : !sessions.data ? (
        <Skeleton className="h-20 rounded-lg" />
      ) : (
        <div className="space-y-3">
          <ul className="divide-y divide-border rounded-lg border border-border">
            {sessions.data.map((session) => {
              const device = describeUserAgent(session.user_agent);
              const Icon = device.mobile ? Smartphone : Monitor;
              return (
                <li key={session.id} className="flex items-center gap-3 px-4 py-3">
                  <Icon className="size-5 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-2 text-sm font-medium text-foreground">
                      {device.label}
                      {session.current && <Badge variant="secondary" className="text-[10px]">Esta sessão</Badge>}
                    </p>
                    <p className="truncate text-xs text-muted-foreground" title={`Criada em ${formatDateTime(session.created_at, locale, timeZone)}`}>
                      {session.ip_address ?? "IP desconhecido"} · ativa {formatRelative(session.last_seen_at, locale)}
                    </p>
                  </div>
                  {!session.current && (
                    <Button variant="ghost" size="sm" onClick={() => revoke.mutate(session.id)} disabled={revoke.isPending}>
                      Encerrar
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
          {others > 0 && (
            <Button variant="outline" size="sm" onClick={() => revokeOthers.mutate()} disabled={revokeOthers.isPending}>
              Encerrar as outras {others} sessões
            </Button>
          )}
        </div>
      )}
    </SettingsSection>
  );
}
