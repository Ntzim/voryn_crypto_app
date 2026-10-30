"use client";

import { Segmented } from "@/components/ui/segmented";
import type { Currency } from "@/lib/api/types";

const OPTIONS: Currency[] = ["BRL", "USD"];

export function CurrencyToggle({ value, onChange }: { value: Currency; onChange: (c: Currency) => void }) {
  return (
    <Segmented label="Moeda de exibição" value={value} onChange={onChange} options={OPTIONS.map((o) => ({ value: o, label: o }))} />
  );
}
