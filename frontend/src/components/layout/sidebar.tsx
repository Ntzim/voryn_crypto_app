"use client";

import { cn } from "cn";
import { ChevronsLeft, ChevronsRight } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Logo } from "@/components/brand/logo";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useUiStore } from "@/lib/stores/ui-store";
import { useHydrated } from "@/lib/use-hydrated";

import { NAV_SECTIONS, isActive, type NavItem } from "./nav-config";

/**
 * md–xl: icon rail. ≥xl: full sidebar unless the user collapsed it.
 * Below md the MobileNav takes over.
 */
export function Sidebar() {
  // Persisted (localStorage) state is applied only after hydration to match the server HTML.
  const hydrated = useHydrated();
  const storedCollapsed = useUiStore((s) => s.sidebarCollapsed);
  const collapsed = hydrated && storedCollapsed;
  const toggle = useUiStore((s) => s.toggleSidebar);
  const pathname = usePathname();
  // `expanded` drives the xl breakpoint only; the rail is always compact below xl.
  const expanded = !collapsed;

  return (
    <aside
      className={cn(
        "sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-sidebar-border bg-sidebar md:flex",
        "w-[68px] transition-[width] duration-200 ease-out",
        expanded && "xl:w-[264px]",
      )}
      aria-label="Navegação principal"
    >
      <div className={cn("flex h-16 items-center px-[18px]", expanded && "xl:px-5")}>
        <Link href="/dashboard" aria-label="Voryn — Dashboard" className="rounded-md outline-offset-4">
          <Logo collapsed className={cn(expanded && "xl:hidden")} />
          <Logo className={cn("hidden", expanded && "xl:inline-flex")} />
        </Link>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 pb-4">
        {NAV_SECTIONS.map((section) => (
          <div key={section.label} className="mt-5 first:mt-2">
            <p
              className={cn(
                "mb-1.5 hidden px-2.5 text-[11px] font-medium tracking-wider text-subtle-foreground uppercase",
                expanded && "xl:block",
              )}
            >
              {section.label}
            </p>
            <ul className="space-y-0.5">
              {section.items.map((item) => (
                <li key={item.href}>
                  <SidebarLink item={item} active={isActive(pathname, item.href)} expanded={expanded} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="hidden border-t border-sidebar-border p-3 xl:block">
        <button
          type="button"
          onClick={toggle}
          className="flex h-9 w-full items-center gap-3 rounded-lg px-2.5 text-sm text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-foreground"
          aria-label={expanded ? "Recolher menu" : "Expandir menu"}
        >
          {expanded ? <ChevronsLeft className="size-4" /> : <ChevronsRight className="size-4" />}
          {expanded && <span>Recolher</span>}
        </button>
      </div>
    </aside>
  );
}

function SidebarLink({ item, active, expanded }: { item: NavItem; active: boolean; expanded: boolean }) {
  const Icon = item.icon;
  const link = (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={cn(
        // Quiet navigation (Linear): the current page is marked by a raised surface and full
        // contrast, not by color; the rest stays a step dimmer than the content.
        "group relative flex h-9 items-center justify-center gap-3 rounded-lg px-2.5 text-[13px] font-medium transition-colors duration-150",
        expanded && "xl:justify-start",
        active
          ? "bg-sidebar-accent text-foreground shadow-[inset_0_1px_0_rgb(255_255_255/0.04)]"
          : "text-sidebar-foreground hover:bg-white/4 hover:text-foreground",
      )}
    >
      <Icon
        className={cn("size-[17px] shrink-0", active ? "text-foreground" : "text-subtle-foreground group-hover:text-foreground")}
        strokeWidth={active ? 2.1 : 1.8}
      />
      <span className={cn("hidden flex-1 truncate", expanded && "xl:inline")}>{item.label}</span>
      {!item.available && (
        <span
          className={cn(
            "hidden rounded-md border border-border px-1.5 py-px text-[10px] font-medium text-subtle-foreground",
            expanded && "xl:inline",
          )}
        >
          Em breve
        </span>
      )}
    </Link>
  );

  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      {/* Tooltips only matter while labels are hidden (rail mode). */}
      <TooltipContent side="right" className={cn(expanded && "xl:hidden")}>
        {item.label}
        {!item.available && " · em breve"}
      </TooltipContent>
    </Tooltip>
  );
}
