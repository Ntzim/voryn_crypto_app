"use client";

import { cn } from "cn";
import Link from "next/link";

import { useMarkets } from "@/lib/b3-queries";

type Tab = { href: string; label: string; active: boolean; market: "CRYPTO" | "B3" };

/**
 * One navigation entry per area; crypto and B3 are tabs inside it. B3 tabs only appear while the
 * market is enabled. Links (not buttons): each tab is its own page, shareable and back-friendly.
 */
function Tabs({ tabs, label }: { tabs: Tab[]; label: string }) {
  const { data: markets } = useMarkets();
  const b3 = markets?.some((m) => m.market === "B3");
  const visible = tabs.filter((t) => t.market === "CRYPTO" || b3);
  if (visible.length < 2) return null;
  return (
    <nav aria-label={label} className="inline-flex w-fit shrink-0 rounded-[10px] bg-surface-sunken p-0.5">
      {visible.map((tab) => (
        <Link
          key={tab.href}
          href={tab.href}
          aria-current={tab.active ? "page" : undefined}
          className={cn(
            "inline-flex h-8 items-center rounded-[8px] px-3 text-xs font-medium whitespace-nowrap transition-colors pointer-coarse:h-10",
            tab.active ? "bg-surface-raised text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}

export function MarketTabs({ current }: { current: "crypto" | "b3" }) {
  return (
    <Tabs
      label="Mercado"
      tabs={[
        { href: "/mercado", label: "Cripto", active: current === "crypto", market: "CRYPTO" },
        { href: "/b3", label: "B3", active: current === "b3", market: "B3" },
      ]}
    />
  );
}

export function OpportunityTabs({ current }: { current: "crypto" | "STOCK" | "FII" }) {
  return (
    <Tabs
      label="Oportunidades por mercado"
      tabs={[
        { href: "/oportunidades", label: "Cripto", active: current === "crypto", market: "CRYPTO" },
        { href: "/oportunidades-b3", label: "Ações", active: current === "STOCK", market: "B3" },
        { href: "/oportunidades-b3?tipo=FII", label: "FIIs", active: current === "FII", market: "B3" },
      ]}
    />
  );
}
