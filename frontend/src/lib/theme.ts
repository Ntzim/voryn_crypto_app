import { useSyncExternalStore } from "react";

/**
 * Theme state: the single place that knows how themes are stored and applied.
 *
 * - The preference ("system" | "light" | "dark") belongs to the user and is saved in their
 *   settings on the server; localStorage only caches it so the first paint is right before
 *   any request (see THEME_SCRIPT). Logging in applies the account's preference, so people
 *   sharing a browser don't inherit each other's theme.
 * - "system" follows `prefers-color-scheme` live.
 * - Applying a theme = toggling the `dark` class on <html> (CSS variables in globals.css do
 *   the rest), `color-scheme` (native controls, scrollbars) and the browser chrome color.
 */

import {
  isThemePreference,
  MEDIA,
  THEME_COLORS,
  THEME_STORAGE_KEY,
  type ResolvedTheme,
  type ThemePreference,
} from "./theme-script";

export {
  isThemePreference,
  THEME_COLORS,
  THEME_SCRIPT,
  THEME_STORAGE_KEY,
  type ResolvedTheme,
  type ThemePreference,
} from "./theme-script";

function readPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return isThemePreference(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

function systemTheme(): ResolvedTheme {
  return window.matchMedia(MEDIA).matches ? "dark" : "light";
}

export function resolveTheme(preference: ThemePreference, system: ResolvedTheme): ResolvedTheme {
  return preference === "system" ? system : preference;
}

type ThemeState = { preference: ThemePreference; resolved: ResolvedTheme };

/**
 * Swap the theme on <html>, then call `done`. With View Transitions the swap runs a frame
 * later (after the old render is captured), so subscribers are only told once the new
 * tokens are live: charts read them right away.
 */
function apply(resolved: ResolvedTheme, done: () => void) {
  const root = document.documentElement;
  if (root.classList.contains("dark") === (resolved === "dark")) {
    done();
    return;
  }
  const swap = () => {
    root.classList.add("theme-switching");
    root.classList.toggle("dark", resolved === "dark");
    root.style.colorScheme = resolved;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLORS[resolved]);
    done();
    // Re-enable transitions after the new styles are computed.
    void getComputedStyle(root).opacity;
    requestAnimationFrame(() => root.classList.remove("theme-switching"));
  };
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reduced && typeof document.startViewTransition === "function") document.startViewTransition(swap);
  else swap();
}

// --------------------------------------------------------------------------- store

const listeners = new Set<() => void>();
let state: ThemeState | null = null;
/** Preference kept in memory when localStorage is unavailable. */
let unsaved: ThemePreference | null = null;

function current(): ThemePreference {
  return unsaved ?? readPreference();
}

function getSnapshot(): ThemeState {
  // First read in the browser: the inline script already applied this theme.
  if (!state) {
    const preference = current();
    state = { preference, resolved: resolveTheme(preference, systemTheme()) };
  }
  return state;
}

function update() {
  const preference = current();
  const next: ThemeState = { preference, resolved: resolveTheme(preference, systemTheme()) };
  apply(next.resolved, () => {
    if (state && state.preference === next.preference && state.resolved === next.resolved) return;
    state = next;
    for (const listener of listeners) listener();
  });
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (listeners.size === 1) {
    // The inline script can run before Next inserts the theme-color meta; sync it now.
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", THEME_COLORS[getSnapshot().resolved]);
    window.matchMedia(MEDIA).addEventListener("change", update);
    // Another tab changed the theme.
    window.addEventListener("storage", onStorage);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      window.matchMedia(MEDIA).removeEventListener("change", update);
      window.removeEventListener("storage", onStorage);
    }
  };
}

function onStorage(event: StorageEvent) {
  if (event.key === THEME_STORAGE_KEY) update();
}

/** Save the preference on this device and apply it now (no reload). */
export function setThemePreference(preference: ThemePreference) {
  try {
    if (preference === "system") localStorage.removeItem(THEME_STORAGE_KEY);
    else localStorage.setItem(THEME_STORAGE_KEY, preference);
    unsaved = null;
  } catch {
    // Storage blocked: the theme still applies for this page view.
    unsaved = preference;
  }
  update();
}

// Server render: the real theme is unknown until the inline script runs, so hydration
// renders a neutral state and components settle right after (see useTheme).
const SERVER_SNAPSHOT = null;

/**
 * Current theme. `null` on the server and during hydration (the server cannot know it),
 * so theme-dependent markup renders identically on both sides and updates right after.
 */
export function useTheme(): ThemeState | null {
  return useSyncExternalStore(subscribe, getSnapshot, () => SERVER_SNAPSHOT);
}
