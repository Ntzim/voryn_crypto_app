"use client";

import { setThemePreference, useTheme } from "@/lib/theme";

import { ThemeToggle } from "./theme-toggle";

/** Signed-out pages: the choice is kept on this device; logging in applies the account's. */
export function DeviceThemeToggle({ className }: { className?: string }) {
  const theme = useTheme();
  return <ThemeToggle resolved={theme?.resolved} onChange={setThemePreference} className={className} />;
}
