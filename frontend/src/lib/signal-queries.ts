"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type {
  Alert,
  AlertInput,
  NotificationList,
  Signal,
  SignalClass,
  SignalHistoryPoint,
  SignalList,
  Timeframe,
} from "@/lib/api/types";
import { useHydrationSafe } from "@/lib/use-hydrated";

/** `color` is a CSS variable: use it in `style` (HTML or SVG), not as an SVG attribute. */
export const SIGNAL_META: Record<SignalClass, { label: string; short: string; tone: string; color: string }> = {
  buy_potential: { label: "Potencial de compra", short: "Compra", tone: "text-signal-buy bg-signal-buy-soft border-transparent", color: "var(--signal-buy)" },
  neutral: { label: "Neutro", short: "Neutro", tone: "text-signal-neutral bg-signal-neutral-soft border-transparent", color: "var(--signal-neutral-dot)" },
  attention: { label: "Atenção", short: "Atenção", tone: "text-signal-watch bg-signal-watch-soft border-transparent", color: "var(--signal-watch)" },
  sell_potential: { label: "Potencial de venda", short: "Venda", tone: "text-signal-sell bg-signal-sell-soft border-transparent", color: "var(--signal-sell)" },
};

export function useSignals(timeframe: Timeframe, watchlistId?: string) {
  return useHydrationSafe(
    useQuery({
      queryKey: ["signals", timeframe, watchlistId ?? null],
      queryFn: ({ signal }) =>
        api<SignalList>("/signals", { query: { timeframe, watchlist_id: watchlistId, limit: 200 }, signal }),
      refetchInterval: 5 * 60_000,
      placeholderData: keepPreviousData,
    }),
  );
}

export function useAssetSignal(slug: string, timeframe: Timeframe) {
  return useHydrationSafe(
    useQuery({
      queryKey: ["signals", "asset", slug, timeframe],
      queryFn: ({ signal }) => api<Signal>(`/signals/${encodeURIComponent(slug)}`, { query: { timeframe }, signal }),
      staleTime: 60_000,
      retry: false,
    }),
  );
}

export function useSignalHistory(slug: string, timeframe: Timeframe) {
  return useHydrationSafe(
    useQuery({
      queryKey: ["signals", "history", slug, timeframe],
      queryFn: ({ signal }) =>
        api<SignalHistoryPoint[]>(`/signals/${encodeURIComponent(slug)}/history`, { query: { timeframe, limit: 90 }, signal }),
      staleTime: 5 * 60_000,
    }),
  );
}

export function useAlerts() {
  return useHydrationSafe(
    useQuery({
      queryKey: ["alerts"],
      queryFn: ({ signal }) => api<Alert[]>("/alerts", { signal }),
    }),
  );
}

export function useNotifications(limit = 30) {
  return useHydrationSafe(
    useQuery({
      queryKey: ["notifications", limit],
      queryFn: ({ signal }) => api<NotificationList>("/notifications", { query: { limit }, signal }),
      // Alerts are evaluated every 5 minutes; checking each minute keeps the bell timely.
      refetchInterval: 60_000,
    }),
  );
}

export function useAlertMutations() {
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["alerts"] });
  };
  return {
    create: useMutation({
      mutationFn: (body: AlertInput) => api<Alert>("/alerts", { method: "POST", body }),
      onSuccess: refresh,
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: string; body: AlertInput }) => api<Alert>(`/alerts/${id}`, { method: "PUT", body }),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api<void>(`/alerts/${id}`, { method: "DELETE" }),
      onSuccess: refresh,
    }),
  };
}

export function useNotificationMutations() {
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["notifications"] });
  };
  return {
    read: useMutation({
      mutationFn: (id: number) => api<void>(`/notifications/${id}/read`, { method: "POST" }),
      onSuccess: refresh,
    }),
    readAll: useMutation({
      mutationFn: () => api<void>("/notifications/read-all", { method: "POST" }),
      onSuccess: refresh,
    }),
  };
}
