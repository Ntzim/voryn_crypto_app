"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { toast } from "sonner";

import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { api, isApiError } from "@/lib/api/client";
import type { SettingsUpdate, User, UserSettings } from "@/lib/api/types";
import { queryKeys, useMe } from "@/lib/queries";

import { SettingsSection } from "./section";

const FALLBACK_TIMEZONES = ["America/Sao_Paulo", "America/New_York", "Europe/Lisbon", "UTC"];

function timeZones(): string[] {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return FALLBACK_TIMEZONES;
  }
}

export function PreferencesSection() {
  const { data: user } = useMe();
  const queryClient = useQueryClient();
  const zones = useMemo(() => timeZones(), []);

  const save = useMutation({
    mutationFn: (changes: SettingsUpdate) => api<UserSettings>("/me/settings", { method: "PATCH", body: changes }),
    onSuccess: (settings) => {
      queryClient.setQueryData<User>(queryKeys.me, (current) => (current ? { ...current, settings } : current));
      // Market values depend on the base currency.
      void queryClient.invalidateQueries({ queryKey: ["market"] });
      toast.success("Preferências salvas.");
    },
    onError: (error) => toast.error(isApiError(error) ? error.message : "Não foi possível salvar."),
  });

  if (!user) return <Skeleton className="h-64 rounded-xl" />;
  const settings = user.settings;

  return (
    <SettingsSection title="Exibição" description="Como valores, datas e horários aparecem na Voryn.">
      <div className="grid max-w-xl gap-5 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="pref-currency">Moeda base</Label>
          <Select value={settings.base_currency} onValueChange={(v) => save.mutate({ base_currency: v as UserSettings["base_currency"] })}>
            <SelectTrigger id="pref-currency" className="h-11 w-full bg-surface">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="BRL">Real brasileiro (BRL)</SelectItem>
              <SelectItem value="USD">Dólar americano (USD)</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="pref-locale">Formato de números e datas</Label>
          <Select value={settings.locale} onValueChange={(v) => save.mutate({ locale: v as UserSettings["locale"] })}>
            <SelectTrigger id="pref-locale" className="h-11 w-full bg-surface">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="pt-BR">Português (Brasil) — 1.234,56</SelectItem>
              <SelectItem value="en-US">English (US) — 1,234.56</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2 sm:col-span-2">
          <Label htmlFor="pref-tz">Fuso horário</Label>
          <Select value={settings.timezone} onValueChange={(v) => save.mutate({ timezone: v })}>
            <SelectTrigger id="pref-tz" className="h-11 w-full bg-surface">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="max-h-72">
              {zones.map((zone) => (
                <SelectItem key={zone} value={zone}>
                  {zone.replaceAll("_", " ")}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <p className="text-xs text-subtle-foreground sm:col-span-2">
          Valores em BRL são convertidos a partir das cotações em USD pela taxa de câmbio mais recente, informada junto aos dados.
        </p>
      </div>
    </SettingsSection>
  );
}
