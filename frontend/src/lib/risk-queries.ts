"use client";

import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { Risk, Scenario, ScenarioInput } from "@/lib/api/types";
import { usePreferences } from "@/lib/queries";
import { useHydrationSafe } from "@/lib/use-hydrated";

export const RISK_WINDOWS = [90, 180, 365] as const;
export type RiskWindowDays = (typeof RISK_WINDOWS)[number];

export function useRisk(portfolioId: string | undefined, window: RiskWindowDays) {
  const { currency } = usePreferences();
  return useHydrationSafe(
    useQuery({
      queryKey: ["risk", portfolioId ?? "", currency, window],
      queryFn: ({ signal }) =>
        api<Risk>(`/portfolios/${portfolioId}/risk`, { query: { currency, window }, signal }),
      enabled: Boolean(portfolioId),
      // Daily closes change once a day; prices inside the amounts every few minutes.
      staleTime: 5 * 60_000,
      placeholderData: keepPreviousData,
    }),
  );
}

export function useScenario(portfolioId: string | undefined) {
  const { currency } = usePreferences();
  return useMutation({
    mutationFn: (body: ScenarioInput) =>
      api<Scenario>(`/portfolios/${portfolioId}/risk/scenario`, { method: "POST", query: { currency }, body }),
  });
}
