import { cn } from "cn";
import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";

/** Settings block: description column on the left (desktop), controls on the right. */
export function SettingsSection({
  title,
  description,
  children,
  className,
}: {
  title: string;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("gap-0 p-5 md:p-6", className)}>
      <div className="grid gap-5 lg:grid-cols-[280px_minmax(0,1fr)] lg:gap-10">
        <div>
          <h2 className="font-heading text-[15px] font-medium text-foreground">{title}</h2>
          {description && <div className="mt-1.5 text-sm text-muted-foreground">{description}</div>}
        </div>
        <div className="min-w-0">{children}</div>
      </div>
    </Card>
  );
}
