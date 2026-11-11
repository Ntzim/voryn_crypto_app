/**
 * Theme constants and the pre-paint script. No React here: the root layout (a Server
 * Component) imports this module; the client store lives in ./theme.ts.
 */

export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "voryn-theme";
export const MEDIA = "(prefers-color-scheme: dark)";
/** Browser chrome (address bar, PWA title bar) per theme; matches --background. */
export const THEME_COLORS: Record<ResolvedTheme, string> = { light: "#f5f5f7", dark: "#0b0f14" };

/**
 * Runs inline in <head> before the body is parsed, so the page never flashes the wrong
 * theme. Kept dependency-free and defensive: storage can be blocked (private mode, policy).
 */
export const THEME_SCRIPT = `(function(){try{var p=localStorage.getItem("${THEME_STORAGE_KEY}");if(p!=="light"&&p!=="dark")p=window.matchMedia("${MEDIA}").matches?"dark":"light";var d=document.documentElement;d.classList.toggle("dark",p==="dark");d.style.colorScheme=p;var m=document.querySelector('meta[name="theme-color"]');if(m)m.setAttribute("content",p==="dark"?"${THEME_COLORS.dark}":"${THEME_COLORS.light}")}catch(e){document.documentElement.classList.add("dark")}})();`;

export function isThemePreference(value: unknown): value is ThemePreference {
  return value === "system" || value === "light" || value === "dark";
}
