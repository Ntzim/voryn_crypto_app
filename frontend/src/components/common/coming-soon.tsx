import { CircleCheck, type LucideIcon } from "lucide-react";

import { PageHeader } from "@/components/common/page-header";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

/**
 * Honest placeholder for roadmap modules: explains what is coming without fake data
 * or controls that do nothing.
 */
export function ComingSoon({
  icon: Icon,
  title,
  description,
  features,
  note,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  features: string[];
  note?: string;
}) {
  return (
    <>
      <PageHeader
        title={
          <span className="inline-flex items-center gap-3">
            {title}
            <Badge variant="outline" className="font-sans text-[11px] font-medium text-muted-foreground">
              Em breve
            </Badge>
          </span>
        }
        description={description}
      />
      <Card className="relative overflow-hidden p-6 md:p-8">
        <div className="flex flex-col gap-6 md:flex-row md:items-start md:gap-10">
          <span className="inline-flex size-12 shrink-0 items-center justify-center rounded-xl border border-border bg-surface">
            <Icon className="size-6 text-primary" aria-hidden />
          </span>
          <div className="flex-1">
            <p className="font-heading text-base font-medium text-foreground">O que este módulo vai entregar</p>
            <ul className="mt-4 grid gap-3 sm:grid-cols-2">
              {features.map((feature) => (
                <li key={feature} className="flex gap-2.5 text-sm text-muted-foreground">
                  <CircleCheck className="mt-0.5 size-4 shrink-0 text-subtle-foreground" aria-hidden />
                  {feature}
                </li>
              ))}
            </ul>
            {note && <p className="mt-6 border-t border-border pt-4 text-xs text-subtle-foreground">{note}</p>}
          </div>
        </div>
      </Card>
    </>
  );
}
