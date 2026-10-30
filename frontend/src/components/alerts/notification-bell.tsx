"use client";

import { cn } from "cn";
import { Bell, CheckCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { NotificationItem } from "@/lib/api/types";
import { formatRelative } from "@/lib/format";
import { usePreferences } from "@/lib/queries";
import { useNotificationMutations, useNotifications } from "@/lib/signal-queries";

export function NotificationItemRow({ item, onOpen }: { item: NotificationItem; onOpen?: () => void }) {
  const { locale } = usePreferences();
  return (
    <button type="button" onClick={onOpen} className="flex w-full gap-3 rounded-md px-2 py-2.5 text-left hover:bg-accent">
      <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", item.read_at ? "bg-transparent" : "bg-primary")} aria-label={item.read_at ? undefined : "não lida"} />
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-foreground">{item.title}</span>
        <span className="mt-0.5 line-clamp-2 block text-xs text-muted-foreground">{item.body}</span>
        <span className="mt-1 block text-[11px] text-subtle-foreground">{formatRelative(item.created_at, locale)}</span>
      </span>
    </button>
  );
}

export function NotificationBell() {
  const router = useRouter();
  const query = useNotifications(10);
  const { read, readAll } = useNotificationMutations();
  const unread = query.data?.unread ?? 0;

  const open = (item: NotificationItem) => {
    if (!item.read_at) read.mutate(item.id);
    const slug = item.data.asset_slug;
    if (typeof slug === "string") router.push(`/analise/${slug}`);
  };

  return (
    <Popover>
      <PopoverTrigger
        className="relative inline-flex size-9 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        aria-label={unread ? `Notificações (${unread} não lidas)` : "Notificações"}
      >
        <Bell className="size-[18px]" />
        {unread > 0 && (
          <span className="num absolute top-1 right-1 inline-flex min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] leading-4 font-semibold text-primary-foreground">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-2">
        <div className="flex items-center justify-between px-2 pt-1 pb-2">
          <p className="text-sm font-medium">Notificações</p>
          {unread > 0 && (
            <Button variant="ghost" size="xs" onClick={() => readAll.mutate()}>
              <CheckCheck /> Marcar como lidas
            </Button>
          )}
        </div>
        {query.data?.items.length ? (
          <ul className="max-h-96 overflow-y-auto">
            {query.data.items.map((item) => (
              <li key={item.id}>
                <NotificationItemRow item={item} onOpen={() => open(item)} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-2 py-6 text-center text-sm text-muted-foreground">Nenhuma notificação ainda.</p>
        )}
        <div className="mt-1 border-t border-border pt-2">
          <Link href="/alertas" className="block rounded-md px-2 py-1.5 text-center text-xs font-medium text-primary-ink hover:bg-accent">
            Gerenciar alertas
          </Link>
        </div>
      </PopoverContent>
    </Popover>
  );
}
