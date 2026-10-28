"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { useHydrationSafe } from "@/lib/use-hydrated";
import type {
  AssetDetail,
  AssetList,
  Currency,
  Locale,
  MarketOverview,
  Session,
  SortKey,
  User,
} from "@/lib/api/types";

/** Market data refreshes server-side every few minutes; polling faster only burns requests. */
const MARKET_REFETCH_MS = 60_000;

export const queryKeys = {
  me: ["me"] as const,
  sessions: ["me", "sessions"] as const,
  marketOverview: (currency: Currency) => ["market", "overview", currency] as const,
  assets: (params: AssetListParams) => ["market", "assets", params] as const,
  asset: (slug: string, currency: Currency) => ["market", "asset", slug, currency] as const,
};

export function useMe() {
  return useHydrationSafe(
    useQuery({
      queryKey: queryKeys.me,
      queryFn: ({ signal }) => api<User>("/me", { signal }),
      staleTime: 5 * 60_000,
    }),
  );
}

export type Preferences = { currency: Currency; locale: Locale; timeZone: string };

const DEFAULT_PREFERENCES: Preferences = {
  currency: "BRL",
  locale: "pt-BR",
  timeZone: "America/Sao_Paulo",
};

export function usePreferences(): Preferences {
  const { data } = useMe();
  if (!data) return DEFAULT_PREFERENCES;
  return {
    currency: data.settings.base_currency,
    locale: data.settings.locale,
    timeZone: data.settings.timezone,
  };
}

export function useSessions() {
  return useHydrationSafe(
    useQuery({
      queryKey: queryKeys.sessions,
      queryFn: ({ signal }) => api<Session[]>("/me/sessions", { signal }),
    }),
  );
}

export function useMarketOverview(currency: Currency) {
  return useHydrationSafe(
    useQuery({
      queryKey: queryKeys.marketOverview(currency),
      queryFn: ({ signal }) =>
        api<MarketOverview>("/market/overview", { query: { currency }, signal }),
      refetchInterval: MARKET_REFETCH_MS,
    }),
  );
}

export type AssetListParams = {
  currency: Currency;
  q: string;
  sort: SortKey;
  order: "asc" | "desc";
  page: number;
  pageSize: number;
  watchlistId?: string;
};

export function useAssets(params: AssetListParams) {
  return useHydrationSafe(
    useQuery({
      queryKey: queryKeys.assets(params),
      queryFn: ({ signal }) =>
        api<AssetList>("/market/assets", {
          query: {
            currency: params.currency,
            q: params.q,
            sort: params.sort,
            order: params.order,
            page: params.page,
            page_size: params.pageSize,
            watchlist_id: params.watchlistId,
          },
          signal,
        }),
      placeholderData: keepPreviousData,
      refetchInterval: MARKET_REFETCH_MS,
    }),
  );
}

export function useAsset(slug: string, currency: Currency) {
  return useHydrationSafe(
    useQuery({
      queryKey: queryKeys.asset(slug, currency),
      queryFn: ({ signal }) =>
        api<AssetDetail>(`/market/assets/${encodeURIComponent(slug)}`, {
          query: { currency },
          signal,
        }),
      refetchInterval: MARKET_REFETCH_MS,
    }),
  );
}
