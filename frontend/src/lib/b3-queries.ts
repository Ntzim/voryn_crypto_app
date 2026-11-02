import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type {
  ExchangeAssetList,
  ExchangeAssetType,
  ExchangeDetail,
  ExchangeHistory,
  ExchangeOverview,
  ExchangeSort,
  MarketInfo,
} from "@/lib/api/types";
import { useHydrationSafe } from "@/lib/use-hydrated";

const BASE = "/market/exchanges/B3";
// Quotes change on the server every sync (30 min on the free plan); no point asking more often.
const REFETCH_MS = 5 * 60_000;

/** Enabled markets. Navigation uses it, so a disabled market simply has no entry. */
export function useMarkets() {
  return useHydrationSafe(
    useQuery({
      queryKey: ["markets"],
      queryFn: ({ signal }) => api<MarketInfo[]>("/market/markets", { signal }),
      staleTime: 5 * 60_000,
    }),
  );
}

export function useB3Overview() {
  return useHydrationSafe(
    useQuery({
      queryKey: ["b3", "overview"],
      queryFn: ({ signal }) => api<ExchangeOverview>(`${BASE}/overview`, { signal }),
      refetchInterval: REFETCH_MS,
    }),
  );
}

export type B3ListParams = {
  q: string;
  assetType: ExchangeAssetType | null;
  sort: ExchangeSort;
  order: "asc" | "desc";
  page: number;
  pageSize: number;
};

export function useB3Assets(params: B3ListParams) {
  return useHydrationSafe(
    useQuery({
      queryKey: ["b3", "assets", params],
      queryFn: ({ signal }) =>
        api<ExchangeAssetList>(`${BASE}/assets`, {
          query: {
            q: params.q,
            asset_type: params.assetType ?? undefined,
            sort: params.sort,
            order: params.order,
            page: params.page,
            page_size: params.pageSize,
          },
          signal,
        }),
      placeholderData: keepPreviousData,
      refetchInterval: REFETCH_MS,
    }),
  );
}

export function useB3Asset(symbol: string) {
  return useHydrationSafe(
    useQuery({
      queryKey: ["b3", "asset", symbol],
      queryFn: ({ signal }) => api<ExchangeDetail>(`${BASE}/assets/${symbol}`, { signal }),
      refetchInterval: REFETCH_MS,
    }),
  );
}

export function useB3History(symbol: string, range: string) {
  return useHydrationSafe(
    useQuery({
      queryKey: ["b3", "history", symbol, range],
      queryFn: ({ signal }) =>
        api<ExchangeHistory>(`${BASE}/assets/${symbol}/history`, { query: { range }, signal }),
      staleTime: 30 * 60_000,
    }),
  );
}
