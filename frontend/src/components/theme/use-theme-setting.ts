"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import type { User, UserSettings } from "@/lib/api/types";
import { queryKeys, useMe } from "@/lib/queries";
import { setThemePreference, useTheme, type ThemePreference } from "@/lib/theme";

/**
 * Theme preference of the signed-in user: applied on this device right away, saved to the
 * account so it follows the person (not the browser) across devices and sessions.
 */
export function useThemeSetting() {
  const theme = useTheme();
  const queryClient = useQueryClient();

  const save = useMutation({
    mutationFn: (preference: ThemePreference) =>
      api<UserSettings>("/me/settings", { method: "PATCH", body: { theme: preference } }),
    onMutate: (preference) => {
      const previous = queryClient.getQueryData<User>(queryKeys.me);
      // Optimistic: ThemeSync compares the account value with the device one, so the cache
      // must already hold the new value or it would switch the theme back.
      queryClient.setQueryData<User>(queryKeys.me, (current) =>
        current ? { ...current, settings: { ...current.settings, theme: preference } } : current,
      );
      setThemePreference(preference);
      return { previous };
    },
    onError: (_error, _preference, context) => {
      if (context?.previous) {
        queryClient.setQueryData(queryKeys.me, context.previous);
        setThemePreference(context.previous.settings.theme);
      }
      toast.error("Não foi possível salvar o tema.");
    },
    onSuccess: (settings) => {
      queryClient.setQueryData<User>(queryKeys.me, (current) => (current ? { ...current, settings } : current));
    },
  });

  return { theme, setTheme: (preference: ThemePreference) => save.mutate(preference) };
}

/** Applies the account's theme on this device whenever it differs (login, other device). */
export function ThemeSync() {
  const { data: user } = useMe();
  const theme = useTheme();
  const accountTheme = user?.settings.theme;
  useEffect(() => {
    if (accountTheme && theme && accountTheme !== theme.preference) setThemePreference(accountTheme);
  }, [accountTheme, theme]);
  return null;
}
