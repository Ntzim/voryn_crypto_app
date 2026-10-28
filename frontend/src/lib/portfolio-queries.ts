"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { useHydrationSafe } from "@/lib/use-hydrated";
import type {
  AssetBrief,
  CsvCommit,
  CsvPreview,
  Currency,
  Exchange,
  InsightList,
  Performance,
  Portfolio,
  PortfolioSummary,
  Transaction,
  TransactionInput,
  TransactionList,
  TxType,
} from "@/lib/api/types";
import { usePreferences } from "@/lib/queries";

/** Valuations follow live prices, which the server refreshes every few minutes. */
const VALUATION_REFETCH_MS = 60_000;

export const portfolioKeys = {
  all: ["portfolio"] as const,
  list: ["portfolio", "list"] as const,
  summary: (id: string, currency: Currency) => ["portfolio", id, "summary", currency] as const,
  performance: (id: string, currency: Currency) => ["portfolio", id, "performance", currency] as const,
  insights: (id: string, currency: Currency) => ["portfolio", id, "insights", currency] as const,
  transactions: (id: string, filters: TransactionFilters) => ["portfolio", id, "transactions", filters] as const,
};

export type TransactionFilters = { type?: TxType; page: number; pageSize: number };

export const TX_LABELS: Record<TxType, string> = {
  buy: "Compra",
  sell: "Venda",
  deposit: "Depósito",
  withdrawal: "Retirada",
  transfer: "Transferência",
  fee: "Taxa",
  conversion: "Conversão",
};

/** The user's default portfolio (created server-side on first access). */
export function usePortfolio() {
  return useHydrationSafe(
    useQuery({
      queryKey: portfolioKeys.list,
      queryFn: ({ signal }) => api<Portfolio[]>("/portfolios", { signal }),
      select: (portfolios) => portfolios[0],
      staleTime: Infinity,
    }),
  );
}

export function useSummary(portfolioId: string | undefined, currency?: Currency) {
  const prefs = usePreferences();
  const c = currency ?? prefs.currency;
  return useHydrationSafe(
    useQuery({
      queryKey: portfolioKeys.summary(portfolioId ?? "", c),
      queryFn: ({ signal }) =>
        api<PortfolioSummary>(`/portfolios/${portfolioId}/summary`, { query: { currency: c }, signal }),
      enabled: Boolean(portfolioId),
      refetchInterval: VALUATION_REFETCH_MS,
      placeholderData: keepPreviousData,
    }),
  );
}

export function usePerformance(portfolioId: string | undefined, currency?: Currency) {
  const prefs = usePreferences();
  const c = currency ?? prefs.currency;
  return useHydrationSafe(
    useQuery({
      queryKey: portfolioKeys.performance(portfolioId ?? "", c),
      queryFn: ({ signal }) =>
        api<Performance>(`/portfolios/${portfolioId}/performance`, { query: { currency: c }, signal }),
      enabled: Boolean(portfolioId),
      refetchInterval: 5 * VALUATION_REFETCH_MS,
      placeholderData: keepPreviousData,
    }),
  );
}

export function useInsights(portfolioId: string | undefined) {
  const { currency } = usePreferences();
  return useHydrationSafe(
    useQuery({
      queryKey: portfolioKeys.insights(portfolioId ?? "", currency),
      queryFn: ({ signal }) =>
        api<InsightList>(`/portfolios/${portfolioId}/insights`, { query: { currency }, signal }),
      enabled: Boolean(portfolioId),
      refetchInterval: 5 * VALUATION_REFETCH_MS,
    }),
  );
}

export function useTransactions(portfolioId: string | undefined, filters: TransactionFilters) {
  return useHydrationSafe(
    useQuery({
      queryKey: portfolioKeys.transactions(portfolioId ?? "", filters),
      queryFn: ({ signal }) =>
        api<TransactionList>(`/portfolios/${portfolioId}/transactions`, {
          query: { type: filters.type, page: filters.page, page_size: filters.pageSize },
          signal,
        }),
      enabled: Boolean(portfolioId),
      placeholderData: keepPreviousData,
    }),
  );
}

export function useExchanges() {
  return useHydrationSafe(
    useQuery({
      queryKey: ["exchanges"],
      queryFn: ({ signal }) => api<Exchange[]>("/exchanges", { signal }),
      staleTime: Infinity,
    }),
  );
}

export function useAssetSearch(q: string) {
  return useHydrationSafe(
    useQuery({
      queryKey: ["market", "search", q],
      queryFn: ({ signal }) => api<AssetBrief[]>("/market/search", { query: { q }, signal }),
      enabled: q.trim().length > 0,
      staleTime: 5 * 60_000,
      placeholderData: keepPreviousData,
    }),
  );
}

/** Any write invalidates every derived figure (positions, returns, insights, lists). */
export function useTransactionMutations(portfolioId: string | undefined) {
  const queryClient = useQueryClient();
  // Not awaited on purpose: callers' own onSuccess (toasts, closing dialogs) must run even if
  // the refetch unmounts the calling component (e.g. deleting the last transaction).
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: portfolioKeys.all });
  };
  const base = `/portfolios/${portfolioId}`;
  return {
    create: useMutation({
      mutationFn: (body: TransactionInput) => api<Transaction>(`${base}/transactions`, { method: "POST", body }),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: string; body: TransactionInput }) =>
        api<Transaction>(`${base}/transactions/${id}`, { method: "PUT", body }),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api<void>(`${base}/transactions/${id}`, { method: "DELETE" }),
      onSuccess: invalidate,
    }),
    preview: useMutation({
      mutationFn: (content: string) =>
        api<CsvPreview>(`${base}/imports/preview`, { method: "POST", body: { content } }),
    }),
    commit: useMutation({
      mutationFn: ({ content, skipInvalid }: { content: string; skipInvalid: boolean }) =>
        api<CsvCommit>(`${base}/imports/commit`, {
          method: "POST",
          body: { content, skip_invalid: skipInvalid },
        }),
      onSuccess: invalidate,
    }),
  };
}
