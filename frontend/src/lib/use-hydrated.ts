import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

/**
 * False on the server and during hydration, true afterwards.
 *
 * App content depends on client-only state (the cached user, their preferences, persisted
 * UI state). Suspense boundaries hydrate late, when that state may already exist, so the
 * first client render would differ from the server HTML — and React does not patch
 * mismatched attributes. Gating on this hook keeps the first client render identical.
 */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
}
