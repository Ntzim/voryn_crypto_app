const FALLBACK = "/dashboard";
// Any origin works: only whether the result stays on it matters.
const BASE = "https://voryn.invalid";

/**
 * Post-login destination: only same-origin paths are allowed (no open redirect).
 *
 * The value is resolved with the URL parser the browser uses, because prefix checks miss
 * inputs it normalizes: it drops tabs and newlines and reads "\" as "/", so "/\t/evil.com"
 * becomes "//evil.com", another site.
 */
export function safeNext(next: string | null): string {
  if (!next || !next.startsWith("/")) return FALLBACK;
  let url: URL;
  try {
    url = new URL(next, BASE);
  } catch {
    return FALLBACK;
  }
  if (url.origin !== BASE) return FALLBACK;
  return `${url.pathname}${url.search}${url.hash}`;
}
