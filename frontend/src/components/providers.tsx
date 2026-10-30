"use client";

import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

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
