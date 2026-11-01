"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Monitor, Moon, Sun } from "lucide-react";
import { useMemo } from "react";
import { toast } from "sonner";

import { useThemeSetting } from "@/components/theme/use-theme-setting";
import { Label } from "@/components/ui/label";
import { Segmented } from "@/components/ui/segmented";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { api, isApiError } from "@/lib/api/client";
import type { SettingsUpdate, User, UserSettings } from "@/lib/api/types";
import { queryKeys, useMe } from "@/lib/queries";
import type { ThemePreference } from "@/lib/theme";

import { SettingsSection } from "./section";

const FALLBACK_TIMEZONES = ["America/Sao_Paulo", "America/New_York", "Europe/Lisbon", "UTC"];

function timeZones(): string[] {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return FALLBACK_TIMEZONES;
  }
}

const THEME_OPTIONS = [
  { value: "system", label: <><Monitor className="size-4" aria-hidden /> Sistema</> },
  { value: "light", label: <><Sun className="size-4" aria-hidden /> Claro</> },
  { value: "dark", label: <><Moon className="size-4" aria-hidden /> Escuro</> },
] satisfies { value: ThemePreference; label: React.ReactNode }[];

export function PreferencesSection() {
  const { data: user } = useMe();
  const { theme, setTheme } = useThemeSetting();
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
        <div className="space-y-2 sm:col-span-2">
          <p className="text-sm leading-none font-medium">
            Tema
          </p>
          <Segmented
            label="Tema"
            value={theme?.preference ?? settings.theme}
            onChange={setTheme}
            options={THEME_OPTIONS}
            className="[&_button]:inline-flex [&_button]:items-center [&_button]:gap-1.5"
          />
          <p className="text-xs text-subtle-foreground">
            “Sistema” acompanha o modo claro ou escuro do seu dispositivo. A escolha fica salva na sua conta.
          </p>
        </div>
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
