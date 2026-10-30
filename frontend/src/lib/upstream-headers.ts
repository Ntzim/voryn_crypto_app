/**
 * Request headers the BFF forwards to the API.
 *
 * The API rate-limits by the client IP it reads from X-Forwarded-For (TRUST_PROXY_HEADERS).
 * Browsers can send that header themselves, and the Railway edge does not reliably replace
 * it, so every client-supplied forwarding header is dropped and X-Forwarded-For is rebuilt
 * with a single address taken from the header the edge does overwrite (X-Real-IP on Railway).
 */

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
  // fetch() already decoded the body; forwarding this would make browsers decode twice.
  "content-encoding",
]);

/** Client-address headers a caller could forge; never forwarded as received. */
const CLIENT_ADDRESS = new Set([
  "forwarded",
  "x-forwarded-for",
  "x-real-ip",
  "x-client-ip",
  "true-client-ip",
  "cf-connecting-ip",
  "fastly-client-ip",
]);

const DEFAULT_CLIENT_IP_HEADER = "x-real-ip";
const IP_PATTERN = /^[0-9a-f:.]{2,45}$/i;

export function isHopByHop(name: string): boolean {
  return HOP_BY_HOP.has(name.toLowerCase());
}

/**
 * `clientIpHeader` names the header set by the trusted edge; "none" forwards no address
 * (the API then sees the BFF's own address, so every client shares one rate-limit bucket).
 */
export function upstreamHeaders(
  incoming: Headers,
  clientIpHeader: string | undefined = DEFAULT_CLIENT_IP_HEADER,
): Headers {
  const headers = new Headers();
  incoming.forEach((value, key) => {
    if (!isHopByHop(key) && !CLIENT_ADDRESS.has(key)) headers.set(key, value);
  });
  const source = (clientIpHeader || DEFAULT_CLIENT_IP_HEADER).toLowerCase();
  if (source !== "none") {
    const ip = incoming.get(source)?.split(",")[0]?.trim();
    if (ip && IP_PATTERN.test(ip)) headers.set("x-forwarded-for", ip);
  }
  return headers;
}
