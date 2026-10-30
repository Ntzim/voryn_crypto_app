"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { ExchangeConnection, ExchangeConnectionInput, ExchangeRecord } from "@/lib/api/types";
import { useHydrationSafe } from "@/lib/use-hydrated";

export function useExchangeConnections(pollMs: number | false = false) {
  return useHydrationSafe(
    useQuery({
      queryKey: ["exchange-connections"],
      queryFn: ({ signal }) => api<ExchangeConnection[]>("/exchange-connections", { signal }),
      refetchInterval: pollMs,
    }),
  );
}

export function useExchangeRecords(id: string, enabled: boolean) {
  return useHydrationSafe(
    useQuery({
      queryKey: ["exchange-connections", id, "records"],
      queryFn: ({ signal }) => api<ExchangeRecord[]>(`/exchange-connections/${id}/records`, { signal }),
      enabled,
    }),
  );
}

export function useExchangeMutations() {
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["exchange-connections"] });
    // Imported transactions change every portfolio view.
    void queryClient.invalidateQueries({ queryKey: ["portfolio"] });
  };
  return {
    connect: useMutation({
      mutationFn: (body: ExchangeConnectionInput) =>
        api<ExchangeConnection>("/exchange-connections", { method: "POST", body }),
      onSuccess: refresh,
    }),
    sync: useMutation({
      mutationFn: (id: string) => api<ExchangeConnection>(`/exchange-connections/${id}/sync`, { method: "POST" }),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api<void>(`/exchange-connections/${id}`, { method: "DELETE" }),
      onSuccess: refresh,
    }),
  };
}
