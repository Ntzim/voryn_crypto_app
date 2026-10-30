"use client";

import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api/client";

function redirectToLogin() {
  const { pathname, search } = window.location;
  if (pathname.startsWith("/entrar")) return;
  const next = encodeURIComponent(pathname + search);
  // A full navigation (not router.push) drops every cached query of the expired session.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign(`/entrar?next=${next}`);
}

function makeClient() {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (error) => {
        // An expired session on any authenticated query sends the user back to login.
        if (error instanceof ApiError && error.status === 401) redirectToLogin();
        // Throttled reads: one notice (fixed id, so parallel queries don't stack toasts).
        // Forms show their own 429 message, so mutations are left to them.
        if (error instanceof ApiError && error.status === 429) {
          const wait = error.retryAfter ? ` Tente novamente em ${error.retryAfter} s.` : "";
          toast.warning(`${error.message}${wait}`, { id: "rate-limited" });
        }
      },
    }),
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: true,
        retry: (failureCount, error) => {
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
          return failureCount < 2;
        },
      },
    },
  });
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(makeClient);
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider delayDuration={200}>{children}</TooltipProvider>
      <Toaster position="top-right" />
    </QueryClientProvider>
  );
}
