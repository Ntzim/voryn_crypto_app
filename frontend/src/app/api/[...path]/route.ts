/**
 * Backend-for-frontend proxy: forwards /api/v1/* to the FastAPI service at request time.
 * Keeps cookies first-party and lets the API live on a private network (see docs/DECISIONS.md).
 */
import type { NextRequest } from "next/server";

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

const UPSTREAM_TIMEOUT_MS = 30_000;

/**
 * API address on the private network. Either a full URL (API_INTERNAL_URL) or, on Railway,
 * the API service's private domain (API_PRIVATE_HOST, a variable reference) and its port.
 */
function apiBaseUrl(): string {
  if (process.env.API_INTERNAL_URL) return process.env.API_INTERNAL_URL;
  const host = process.env.API_PRIVATE_HOST;
  if (host) {
    const bracketed = host.includes(":") && !host.startsWith("[") ? `[${host}]` : host;
    return `http://${bracketed}:${process.env.API_PRIVATE_PORT ?? "8000"}`;
  }
  return "http://localhost:8010";
}

function errorResponse(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message, details: null }, request_id: null }, { status });
}

async function forward(request: NextRequest, ctx: RouteContext<"/api/[...path]">): Promise<Response> {
  const { path } = await ctx.params;
  if (path[0] !== "v1" || path.some((segment) => segment === "." || segment === "..")) {
    return errorResponse(404, "not_found", "Recurso não encontrado.");
  }
  const target = new URL(
    `/api/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`,
    apiBaseUrl(),
  );

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key)) headers.set(key, value);
  });

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  // The timeout covers the wait for response headers only: streamed bodies (Voryn AI replies)
  // may legitimately take longer. A client disconnect cancels the upstream request too.
  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), UPSTREAM_TIMEOUT_MS);
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      redirect: "manual",
      cache: "no-store",
      signal: AbortSignal.any([timeout.signal, request.signal]),
    });
  } catch {
    return errorResponse(
      502,
      "upstream_unavailable",
      "Não foi possível conectar aos servidores da Voryn. Tente novamente em instantes.",
    );
  } finally {
    clearTimeout(timer);
  }

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key) && key !== "set-cookie") responseHeaders.set(key, value);
  });
  for (const cookie of upstream.headers.getSetCookie()) responseHeaders.append("set-cookie", cookie);

  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export { forward as DELETE, forward as GET, forward as PATCH, forward as POST, forward as PUT };
