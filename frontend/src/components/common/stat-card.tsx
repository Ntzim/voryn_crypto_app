import { cn } from "cn";
import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Info } from "lucide-react";

export function StatCard({
  label,
  value,
  hint,
  footer,
  loading,
  className,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  footer?: ReactNode;
  loading?: boolean;
  className?: string;
}) {
  return (
    <Card className={cn("gap-0 px-5 py-4", className)}>
      <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        {label}
        {hint && (
          <Tooltip>
            <TooltipTrigger aria-label={`Sobre: ${label}`} className="text-subtle-foreground hover:text-foreground">
              <Info className="size-3.5" />
            </TooltipTrigger>
            <TooltipContent className="max-w-64">{hint}</TooltipContent>
          </Tooltip>
        )}
      </div>
      {loading ? (
        <Skeleton className="mt-2.5 h-7 w-32" />
      ) : (
        <div className="num mt-1.5 font-heading text-xl font-semibold text-foreground md:text-[22px]">{value}</div>
      )}
      {footer && <div className="mt-2 text-xs text-muted-foreground">{loading ? <Skeleton className="h-4 w-24" /> : footer}</div>}
    </Card>
  );
}
