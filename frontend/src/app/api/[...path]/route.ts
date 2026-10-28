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

function apiBaseUrl(): string {
  return process.env.API_INTERNAL_URL ?? "http://localhost:8010";
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
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      redirect: "manual",
      cache: "no-store",
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch {
    return errorResponse(
      502,
      "upstream_unavailable",
      "Não foi possível conectar aos servidores da Voryn. Tente novamente em instantes.",
    );
  }

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key) && key !== "set-cookie") responseHeaders.set(key, value);
  });
  for (const cookie of upstream.headers.getSetCookie()) responseHeaders.append("set-cookie", cookie);

  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export { forward as DELETE, forward as GET, forward as PATCH, forward as POST, forward as PUT };
