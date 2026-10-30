import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "voryn_session";

/**
 * Optimistic route guard: without a session cookie, app routes redirect to login.
 * The API still validates every request; a stale cookie is caught there (401 → login).
 */
export function proxy(request: NextRequest) {
  if (request.cookies.has(SESSION_COOKIE)) return NextResponse.next();
  const url = request.nextUrl.clone();
  url.pathname = "/entrar";
  url.search = "";
  const next = request.nextUrl.pathname + request.nextUrl.search;
  if (next !== "/") url.searchParams.set("next", next);
  return NextResponse.redirect(url);
}

export const config = {
  matcher: [
    "/",
    "/dashboard/:path*",
    "/carteira/:path*",
    "/mercado/:path*",
    "/analise/:path*",
    "/oportunidades/:path*",
    "/voryn-ai/:path*",
    "/risco/:path*",
    "/estrategias/:path*",
    "/alertas/:path*",
    "/configuracoes/:path*",
  ],
};
