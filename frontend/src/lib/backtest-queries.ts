"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { Backtest, BacktestInput, BacktestStrategy, BacktestSummary } from "@/lib/api/types";
import { useHydrationSafe } from "@/lib/use-hydrated";

export function useBacktestStrategies() {
  return useHydrationSafe(
    useQuery({
      queryKey: ["backtests", "strategies"],
      queryFn: ({ signal }) => api<BacktestStrategy[]>("/backtests/strategies", { signal }),
      staleTime: Infinity,
    }),
  );
}

export function useBacktests() {
  return useHydrationSafe(
    useQuery({
      queryKey: ["backtests", "list"],
      queryFn: ({ signal }) => api<BacktestSummary[]>("/backtests", { signal }),
      // Keep the history fresh while any run is still being processed.
      refetchInterval: (query) =>
        query.state.data?.some((r) => r.status === "queued" || r.status === "running") ? 3000 : false,
    }),
  );
}

export function useBacktest(id: string | null) {
  return useHydrationSafe(
    useQuery({
      queryKey: ["backtests", "run", id],
      queryFn: ({ signal }) => api<Backtest>(`/backtests/${id}`, { signal }),
      enabled: id !== null,
      retry: false,
      refetchInterval: (query) => {
        const s = query.state.data?.status;
        return s === "queued" || s === "running" ? 1500 : false;
      },
    }),
  );
}

export function useBacktestMutations() {
  const queryClient = useQueryClient();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["backtests", "list"] });
  return {
    create: useMutation({
      mutationFn: (body: BacktestInput) => api<Backtest>("/backtests", { method: "POST", body }),
      onSuccess: (run) => {
        queryClient.setQueryData(["backtests", "run", run.id], run);
        refresh();
      },
    }),
    remove: useMutation({
      mutationFn: (id: string) => api<void>(`/backtests/${id}`, { method: "DELETE" }),
      onSuccess: (_d, id) => {
        queryClient.removeQueries({ queryKey: ["backtests", "run", id] });
        refresh();
      },
    }),
  };
}
