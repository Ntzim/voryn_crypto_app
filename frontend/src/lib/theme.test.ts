import { describe, expect, it } from "vitest";

import { readChartPalette, withAlpha } from "./chart-theme";
import { resolveTheme } from "./theme";
import { isThemePreference, THEME_COLORS, THEME_SCRIPT, THEME_STORAGE_KEY } from "./theme-script";

/** Runs the inline <head> script against a minimal fake browser. */
function runScript({ stored, systemDark, storageThrows = false }: { stored: string | null; systemDark: boolean; storageThrows?: boolean }) {
  const classes = new Set<string>();
  const meta = { content: "", setAttribute: (_: string, v: string) => (meta.content = v) };
  const root = {
    classList: {
      toggle: (name: string, on: boolean) => (on ? classes.add(name) : classes.delete(name)),
      add: (name: string) => classes.add(name),
    },
    style: { colorScheme: "" },
  };
  const window = { matchMedia: () => ({ matches: systemDark }) };
  const localStorage = {
    getItem: (key: string) => {
      if (storageThrows) throw new Error("blocked");
      return key === THEME_STORAGE_KEY ? stored : null;
    },
  };
  const document = { documentElement: root, querySelector: () => meta };
  new Function("window", "document", "localStorage", THEME_SCRIPT)(window, document, localStorage);
  return { dark: classes.has("dark"), colorScheme: root.style.colorScheme, themeColor: meta.content };
}

describe("THEME_SCRIPT (applied before first paint)", () => {
  it("uses the saved preference over the system setting", () => {
    expect(runScript({ stored: "light", systemDark: true })).toEqual({ dark: false, colorScheme: "light", themeColor: THEME_COLORS.light });
    expect(runScript({ stored: "dark", systemDark: false })).toEqual({ dark: true, colorScheme: "dark", themeColor: THEME_COLORS.dark });
  });

  it("follows prefers-color-scheme without a valid saved preference", () => {
    expect(runScript({ stored: null, systemDark: true }).dark).toBe(true);
    expect(runScript({ stored: null, systemDark: false }).dark).toBe(false);
    expect(runScript({ stored: "sepia", systemDark: false }).dark).toBe(false);
  });

  it("falls back to dark when storage is blocked", () => {
    expect(runScript({ stored: null, systemDark: false, storageThrows: true }).dark).toBe(true);
  });
});

describe("theme helpers", () => {
  it("resolves system against the device setting", () => {
    expect(resolveTheme("system", "dark")).toBe("dark");
    expect(resolveTheme("system", "light")).toBe("light");
    expect(resolveTheme("light", "dark")).toBe("light");
  });

  it("validates preferences", () => {
    expect(["system", "light", "dark"].every(isThemePreference)).toBe(true);
    expect(isThemePreference("auto")).toBe(false);
    expect(isThemePreference(null)).toBe(false);
  });
});

describe("chart palette", () => {
  it("builds rgba colors from hex tokens", () => {
    expect(withAlpha("#585bef", 0.28)).toBe("rgba(88, 91, 239, 0.28)");
    expect(withAlpha(" #fff ", 0.5)).toBe("rgba(255, 255, 255, 0.5)");
    expect(withAlpha("not-a-color", 0.5)).toBe("not-a-color");
  });

  it("reads every color from the theme tokens", () => {
    const tokens: Record<string, string> = {
      "--foreground": "#1d1d1f",
      "--chart-axis": "#6b6c74",
      "--chart-up": "#0f9f6e",
      "--chart-down": "#e0364c",
      "--chart-1": "#585bef",
      "--popover": "#ffffff",
    };
    const palette = readChartPalette({ getPropertyValue: (name: string) => ` ${tokens[name] ?? ""}` });
    expect(palette.text).toBe("#6b6c74");
    expect(palette.up).toBe("#0f9f6e");
    expect(palette.grid).toBe("rgba(29, 29, 31, 0.06)");
    expect(palette.series[0]).toBe("#585bef");
    expect(palette.tooltip.background).toBe("#ffffff");
  });
});
