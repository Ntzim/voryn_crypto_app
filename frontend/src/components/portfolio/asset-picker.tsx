"use client";

import { cn } from "cn";
import { ChevronsUpDown, Search } from "lucide-react";
import { useState } from "react";

import { AssetIcon } from "@/components/common/asset-icon";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { AssetBrief } from "@/lib/api/types";
import { useAssetSearch } from "@/lib/portfolio-queries";

export function AssetPicker({
  value,
  onChange,
  id,
  invalid,
}: {
  value: AssetBrief | null;
  onChange: (asset: AssetBrief) => void;
  id?: string;
  invalid?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const results = useAssetSearch(q);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        id={id}
        aria-invalid={invalid || undefined}
        className={cn(
          "flex h-11 w-full items-center gap-2.5 rounded-lg border border-input bg-surface px-3 text-left text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
          invalid && "border-destructive",
        )}
      >
        {value ? (
          <>
            <AssetIcon src={value.image_url} symbol={value.symbol} size={20} />
            <span className="flex-1 truncate text-foreground">{value.name}</span>
            <span className="text-xs text-muted-foreground">{value.symbol}</span>
          </>
        ) : (
          <span className="flex-1 text-muted-foreground">Selecionar ativo</span>
        )}
        <ChevronsUpDown className="size-4 text-subtle-foreground" />
      </PopoverTrigger>
      <PopoverContent className="w-(--radix-popover-trigger-width) p-2" align="start">
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-subtle-foreground" />
          <Input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Buscar por nome ou símbolo"
            className="h-9 pl-8"
            aria-label="Buscar ativo"
          />
        </div>
        <ul className="mt-2 max-h-64 overflow-y-auto" role="listbox">
          {!q.trim() ? (
            <li className="px-2 py-3 text-xs text-muted-foreground">Digite para buscar entre os ativos acompanhados.</li>
          ) : results.data?.length === 0 ? (
            <li className="px-2 py-3 text-xs text-muted-foreground">
              Nenhum ativo encontrado. A Voryn acompanha os 100 maiores ativos por capitalização.
            </li>
          ) : (
            results.data?.map((asset) => (
              <li key={asset.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={value?.id === asset.id}
                  onClick={() => {
                    onChange(asset);
                    setOpen(false);
                    setQ("");
                  }}
                  className="flex w-full items-center gap-2.5 rounded-md px-2 py-2 text-left text-sm hover:bg-accent"
                >
                  <AssetIcon src={asset.image_url} symbol={asset.symbol} size={20} />
                  <span className="flex-1 truncate text-foreground">{asset.name}</span>
                  <span className="text-xs text-muted-foreground">{asset.symbol}</span>
                </button>
              </li>
            ))
          )}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
