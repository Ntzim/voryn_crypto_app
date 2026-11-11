"use client";

import { useQuery } from "@tanstack/react-query";
import { cn } from "cn";
import { CornerDownLeft, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api/client";
import type { InstrumentHit } from "@/lib/api/types";

import { NAV_ITEMS } from "./nav-config";

type Result = { key: string; label: string; detail: string; href: string; group: "Ativos" | "Ir para" };

function instrumentHref(hit: InstrumentHit): string {
  return hit.market === "B3" ? `/b3/${hit.symbol}` : `/mercado/${hit.slug}`;
}

const MARKET_LABEL: Record<string, string> = { CRYPTO: "Cripto", B3: "B3", US: "EUA" };
const TYPE_LABEL: Record<string, string> = { STOCK: "Ação", FII: "FII", ETF: "ETF", BDR: "BDR", CRYPTO: "Cripto" };

/** Global search and navigation: instruments across the enabled markets plus every area. */
export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [index, setIndex] = useState(0);
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    const id = setTimeout(() => setDebounced(query.trim()), 200);
    return () => clearTimeout(id);
  }, [query]);

  const hits = useQuery({
    queryKey: ["instrument-search", debounced],
    queryFn: ({ signal }) => api<InstrumentHit[]>("/market/instruments/search", { query: { q: debounced, limit: 8 }, signal }),
    enabled: open && debounced.length > 0,
    staleTime: 60_000,
  });

  const results = useMemo<Result[]>(() => {
    const q = query.trim().toLocaleLowerCase("pt-BR");
    const pages = NAV_ITEMS.filter((item) => !q || item.label.toLocaleLowerCase("pt-BR").includes(q)).map<Result>((item) => ({
      key: `nav:${item.href}`,
      label: item.label,
      detail: "Página",
      href: item.href,
      group: "Ir para",
    }));
    const assets = (q ? (hits.data ?? []) : []).map<Result>((hit) => ({
      key: `asset:${hit.id}`,
      label: `${hit.symbol} · ${hit.name}`,
      detail: `${MARKET_LABEL[hit.market] ?? hit.market} · ${TYPE_LABEL[hit.asset_type] ?? hit.asset_type}`,
      href: instrumentHref(hit),
      group: "Ativos",
    }));
    return [...assets, ...pages];
  }, [hits.data, query]);

  const go = (result: Result | undefined) => {
    if (!result) return;
    onOpenChange(false);
    setQuery("");
    router.push(result.href);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setIndex((i) => (results.length ? (i + step + results.length) % results.length : 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      go(results[Math.min(index, results.length - 1)]);
    }
  };

  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${index}"]`)?.scrollIntoView({ block: "nearest" });
  }, [index]);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) setQuery("");
      }}
    >
      <DialogContent className="gap-0 overflow-hidden p-0 sm:max-w-xl" showCloseButton={false}>
        <DialogTitle className="sr-only">Buscar</DialogTitle>
        <DialogDescription className="sr-only">Busque um ativo, FII ou página e pressione Enter.</DialogDescription>
        <div className="flex items-center gap-2 border-b border-border px-4">
          <Search className="size-4 shrink-0 text-subtle-foreground" strokeWidth={1.5} aria-hidden />
          <input
            autoFocus
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setIndex(0);
            }}
            onKeyDown={onKeyDown}
            placeholder="Buscar ativo, FII ou comando"
            aria-label="Buscar ativo, FII ou comando"
            role="combobox"
            aria-expanded
            aria-controls="command-results"
            aria-activedescendant={results[index] ? `command-${index}` : undefined}
            className="h-12 w-full bg-transparent text-sm text-foreground outline-none placeholder:text-subtle-foreground"
            maxLength={64}
          />
        </div>
        <ul ref={listRef} id="command-results" role="listbox" className="max-h-[60dvh] overflow-y-auto p-2">
          {results.length === 0 ? (
            <li className="px-3 py-6 text-center text-sm text-muted-foreground">{hits.isFetching ? "Buscando…" : "Nada encontrado."}</li>
          ) : (
            results.map((result, i) => (
              <li key={result.key} id={`command-${i}`} role="option" aria-selected={i === index} data-index={i}>
                {(i === 0 || results[i - 1].group !== result.group) && (
                  <p className="overline px-3 pt-2 pb-1 text-subtle-foreground">{result.group}</p>
                )}
                <button
                  type="button"
                  onMouseEnter={() => setIndex(i)}
                  onClick={() => go(result)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-[10px] px-3 py-2.5 text-left text-sm",
                    i === index ? "bg-brand-soft text-brand-strong-text" : "text-foreground",
                  )}
                >
                  <span className="min-w-0 flex-1 truncate">{result.label}</span>
                  <span className="shrink-0 text-xs text-subtle-foreground">{result.detail}</span>
                  {i === index && <CornerDownLeft className="size-3.5 shrink-0" aria-hidden />}
                </button>
              </li>
            ))
          )}
        </ul>
      </DialogContent>
    </Dialog>
  );
}

/** Ctrl/⌘ K anywhere opens the palette. */
export function useCommandShortcut(open: () => void) {
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        open();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
}
