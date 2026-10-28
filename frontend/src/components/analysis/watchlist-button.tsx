"use client";

import { cn } from "cn";
import { Check, ListPlus, Star } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { isApiError } from "@/lib/api/client";
import { useWatchlistMutations, useWatchlists } from "@/lib/analysis-queries";

/** Star toggles the default "Favoritos" list. */
export function FavoriteStar({ assetId, className }: { assetId: string; className?: string }) {
  const { data } = useWatchlists();
  const { toggle } = useWatchlistMutations();
  const favorites = data?.find((w) => w.is_default);
  const member = favorites?.asset_ids.includes(assetId) ?? false;
  return (
    <button
      type="button"
      disabled={!favorites}
      aria-pressed={member}
      aria-label={member ? "Remover dos favoritos" : "Adicionar aos favoritos"}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        if (favorites) toggle.mutate({ list: favorites, assetId, member });
      }}
      className={cn("relative z-10 inline-flex size-7 items-center justify-center rounded-md transition-colors hover:bg-accent", className)}
    >
      <Star className={cn("size-4", member ? "fill-warning text-warning" : "text-subtle-foreground")} />
    </button>
  );
}

/** Full control: membership in every list + create a new list. */
export function WatchlistMenu({ assetId }: { assetId: string }) {
  const { data } = useWatchlists();
  const { toggle, create } = useWatchlistMutations();
  const [name, setName] = useState("");
  const inAny = data?.some((w) => w.asset_ids.includes(assetId)) ?? false;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    create.mutate(name, {
      onSuccess: (list) => {
        toggle.mutate({ list, assetId, member: false });
        setName("");
        toast.success(`Lista “${list.name}” criada.`);
      },
      onError: (error) => toast.error(isApiError(error) ? error.message : "Não foi possível criar a lista."),
    });
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline">
          <Star className={cn(inAny && "fill-warning text-warning")} /> Listas
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 p-2">
        <p className="px-2 pt-1 pb-2 text-xs font-medium text-muted-foreground">Acompanhar em</p>
        <ul>
          {data?.map((list) => {
            const member = list.asset_ids.includes(assetId);
            return (
              <li key={list.id}>
                <button
                  type="button"
                  role="menuitemcheckbox"
                  aria-checked={member}
                  onClick={() => toggle.mutate({ list, assetId, member })}
                  className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm hover:bg-accent"
                >
                  <span className={cn("flex size-4 items-center justify-center rounded border", member ? "border-primary bg-primary text-primary-foreground" : "border-border-strong")}>
                    {member && <Check className="size-3" />}
                  </span>
                  <span className="flex-1 truncate">{list.name}</span>
                  <span className="text-xs text-subtle-foreground">{list.asset_ids.length}</span>
                </button>
              </li>
            );
          })}
        </ul>
        <form onSubmit={submit} className="mt-2 flex gap-1.5 border-t border-border pt-2">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Nova lista" maxLength={40} className="h-8" aria-label="Nome da nova lista" />
          <Button type="submit" size="icon-sm" variant="secondary" disabled={!name.trim() || create.isPending} aria-label="Criar lista">
            <ListPlus />
          </Button>
        </form>
      </PopoverContent>
    </Popover>
  );
}
