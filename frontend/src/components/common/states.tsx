import { cn } from "cn";
import { RefreshCw, TriangleAlert, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon: LucideIcon;
  title: string;
  description: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center px-6 py-12 text-center", className)}>
      <span className="mb-4 inline-flex size-11 items-center justify-center rounded-xl border border-border bg-surface">
        <Icon className="size-5 text-muted-foreground" aria-hidden />
      </span>
      <p className="font-heading text-base font-medium text-foreground">{title}</p>
      <div className="mt-1.5 max-w-sm text-sm text-muted-foreground">{description}</div>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  const message =
    error instanceof ApiError ? error.message : "Não foi possível carregar estes dados.";
  return (
    <EmptyState
      icon={TriangleAlert}
      title="Algo não saiu como esperado"
      description={message}
      className={className}
      action={
        onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCw /> Tentar novamente
          </Button>
        )
      }
    />
  );
}
