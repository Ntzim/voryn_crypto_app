import { Skeleton } from "@/components/ui/skeleton";

type Variant = "dashboard" | "list" | "detail" | "panel";

/**
 * Server-rendered placeholder shown while a page's JavaScript and data load. It mirrors the
 * shape of the real page, so a slow connection shows structure instead of a blank screen and
 * nothing jumps when the content arrives.
 */
export function PageSkeleton({ variant = "panel", label }: { variant?: Variant; label: string }) {
  return (
    <div role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">Carregando {label}…</span>
      <div aria-hidden className="space-y-4">
        <div className="mb-5 space-y-2 md:mb-7">
          <Skeleton className="h-3 w-32" />
          <Skeleton className="h-7 w-44" />
        </div>
        {variant === "dashboard" && <DashboardShape />}
        {variant === "list" && <ListShape />}
        {variant === "detail" && <DetailShape />}
        {variant === "panel" && <PanelShape />}
      </div>
    </div>
  );
}

function Surface({ className = "", children }: { className?: string; children: React.ReactNode }) {
  return <div className={`rounded-2xl bg-card ring-1 ring-white/6 p-5 ${className}`}>{children}</div>;
}

function Rows({ count }: { count: number }) {
  return (
    <div className="space-y-4">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="size-8 rounded-full" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-3.5 w-28" />
            <Skeleton className="h-3 w-16" />
          </div>
          <div className="space-y-1.5">
            <Skeleton className="ml-auto h-3.5 w-20" />
            <Skeleton className="ml-auto h-3 w-12" />
          </div>
        </div>
      ))}
    </div>
  );
}

function DashboardShape() {
  return (
    <>
      <Surface>
        <Skeleton className="h-3 w-20" />
        <Skeleton className="mt-3 h-10 w-56" />
        <Skeleton className="mt-3 h-4 w-48" />
        <div className="mt-5 grid grid-cols-2 gap-6 border-t border-border pt-4">
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
        </div>
      </Surface>
      <div className="grid gap-4 lg:grid-cols-3">
        <Surface className="lg:col-span-2">
          <Skeleton className="h-64 w-full" />
        </Surface>
        <Surface>
          <Rows count={4} />
        </Surface>
      </div>
    </>
  );
}

function ListShape() {
  return (
    <>
      <div className="flex flex-col gap-2 sm:flex-row">
        <Skeleton className="h-10 w-full sm:max-w-sm" />
        <Skeleton className="h-10 w-full sm:w-48" />
      </div>
      <Surface>
        <Rows count={8} />
      </Surface>
    </>
  );
}

function DetailShape() {
  return (
    <>
      <div className="flex items-center gap-3">
        <Skeleton className="size-11 rounded-full" />
        <div className="space-y-2">
          <Skeleton className="h-6 w-36" />
          <Skeleton className="h-4 w-28" />
        </div>
      </div>
      <Surface>
        <Skeleton className="h-80 w-full" />
      </Surface>
    </>
  );
}

function PanelShape() {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Surface className="lg:col-span-2">
        <Skeleton className="h-56 w-full" />
      </Surface>
      <Surface>
        <Rows count={4} />
      </Surface>
    </div>
  );
}
