"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { Analysis, Timeframe, Watchlist } from "@/lib/api/types";

export const TIMEFRAMES: { value: Timeframe; label: string }[] = [
  { value: "15m", label: "15m" },
  { value: "1h", label: "1h" },
  { value: "4h", label: "4h" },
  { value: "1d", label: "1D" },
  { value: "1w", label: "1S" },
];

/** Roughly one candle period, capped; the server caches candles per timeframe as well. */
const REFRESH_MS: Record<Timeframe, number> = {
  "15m": 60_000,
  "1h": 120_000,
  "4h": 300_000,
  "1d": 600_000,
  "1w": 1_800_000,
};

export function useAnalysis(slug: string, timeframe: Timeframe) {
  return useQuery({
    queryKey: ["analysis", slug, timeframe],
    queryFn: ({ signal }) =>
      api<Analysis>(`/market/assets/${encodeURIComponent(slug)}/analysis`, { query: { timeframe }, signal }),
    refetchInterval: REFRESH_MS[timeframe],
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

const WATCHLISTS = ["watchlists"] as const;

export function useWatchlists() {
  return useQuery({
    queryKey: WATCHLISTS,
    queryFn: ({ signal }) => api<Watchlist[]>("/watchlists", { signal }),
    staleTime: 5 * 60_000,
  });
}

export function useWatchlistMutations() {
  const queryClient = useQueryClient();

  const toggle = useMutation({
    mutationFn: ({ list, assetId, member }: { list: Watchlist; assetId: string; member: boolean }) =>
      api<void>(`/watchlists/${list.id}/assets/${assetId}`, { method: member ? "DELETE" : "PUT" }),
    // Optimistic: the star reacts instantly; rolled back on failure.
    onMutate: async ({ list, assetId, member }) => {
      await queryClient.cancelQueries({ queryKey: WATCHLISTS });
      const previous = queryClient.getQueryData<Watchlist[]>(WATCHLISTS);
      queryClient.setQueryData<Watchlist[]>(WATCHLISTS, (lists) =>
        lists?.map((w) =>
          w.id !== list.id
            ? w
            : { ...w, asset_ids: member ? w.asset_ids.filter((id) => id !== assetId) : [...w.asset_ids, assetId] },
        ),
      );
      return { previous };
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(WATCHLISTS, context.previous);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: WATCHLISTS });
      void queryClient.invalidateQueries({ queryKey: ["market", "assets"] });
    },
  });

  const create = useMutation({
    mutationFn: (name: string) => api<Watchlist>("/watchlists", { method: "POST", body: { name } }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: WATCHLISTS });
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => api<void>(`/watchlists/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: WATCHLISTS });
    },
  });

  return { toggle, create, remove };
}
