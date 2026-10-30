"use client";

import { cn } from "cn";
import { Info, ShieldAlert, TriangleAlert } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Insight } from "@/lib/api/types";

const STYLE = {
  info: { icon: Info, className: "text-primary bg-primary/10" },
  attention: { icon: TriangleAlert, className: "text-warning bg-warning/10" },
  risk: { icon: ShieldAlert, className: "text-destructive bg-destructive/10" },
} as const;

export function InsightsPanel({
  items,
  loading,
  title = "Insights da carteira",
  emptyText = "Nenhum ponto de atenção identificado pelas regras atuais (concentração, variação relevante, posições abaixo do preço médio e correlação).",
}: {
  items: Pick<Insight, "id" | "severity" | "title" | "message" | "basis">[] | undefined;
  loading?: boolean;
  title?: string;
  emptyText?: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-heading text-sm font-medium">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {loading || !items ? (
          <div className="space-y-3">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">{emptyText}</p>
        ) : (
          <ul className="space-y-3">
            {items.map((item) => {
              const { icon: Icon, className } = STYLE[item.severity];
              return (
                <li key={item.id} className="flex gap-3 rounded-lg border border-border bg-surface p-3">
                  <span className={cn("mt-0.5 inline-flex size-7 shrink-0 items-center justify-center rounded-md", className)}>
                    <Icon className="size-4" aria-hidden />
                  </span>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground">{item.title}</p>
                    <p className="mt-0.5 text-sm text-muted-foreground">{item.message}</p>
                    <Tooltip>
                      <TooltipTrigger className="mt-1 text-[11px] text-subtle-foreground underline decoration-dotted underline-offset-2 hover:text-foreground">
                        Como é calculado
                      </TooltipTrigger>
                      <TooltipContent className="max-w-72">{item.basis}</TooltipContent>
                    </Tooltip>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
