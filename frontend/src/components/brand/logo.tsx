import { cn } from "cn";

/** Voryn mark: two converging strokes forming a "V" — signal meeting evidence. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      className={cn("size-7 shrink-0", className)}
    >
      <rect width="32" height="32" rx="8" fill="#151D28" />
      <rect x="0.5" y="0.5" width="31" height="31" rx="7.5" stroke="rgb(148 163 184 / 0.18)" />
      <path d="M8.5 9.5 15.2 22.6" stroke="#6366F1" strokeWidth="3" strokeLinecap="round" />
      <path d="M23.5 9.5 16.8 22.6" stroke="#8B5CF6" strokeWidth="3" strokeLinecap="round" />
      <circle cx="16" cy="24" r="1.6" fill="#F8FAFC" />
    </svg>
  );
}

export function Logo({ className, collapsed = false }: { className?: string; collapsed?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark />
      {!collapsed && (
        <span className="font-heading text-[15px] font-semibold tracking-[0.24em] text-foreground">
          VORYN
        </span>
      )}
    </span>
  );
}
