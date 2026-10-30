"use client";

import { cn } from "cn";
import { Ellipsis, LogOut } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

import { NAV_ITEMS, NAV_SECTIONS, isActive } from "./nav-config";
import { useLogout } from "./use-logout";

const PRIMARY = NAV_ITEMS.filter((item) => item.mobilePrimary);

/** Bottom tab bar for phones: thumb-reachable access to the most used areas. */
export function MobileNav() {
  return <MobileNavBar pathname={usePathname()} />;
}

/**
 * The bar itself. Reading the URL suspends, so the app shell renders this with
 * `pathname={null}` as the Suspense fallback: the bar is in the first HTML instead of
 * appearing only once the JavaScript has loaded.
 */
export function MobileNavBar({ pathname }: { pathname: string | null }) {
  const [open, setOpen] = useState(false);
  const logout = useLogout();
  const moreActive = pathname !== null && !PRIMARY.some((item) => isActive(pathname, item.href));

  return (
    <nav
      aria-label="Navegação principal"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-background/90 pb-safe backdrop-blur-lg md:hidden"
    >
      <ul className="mx-auto grid h-16 max-w-md grid-cols-5">
        {PRIMARY.map((item) => {
          const active = pathname !== null && isActive(pathname, item.href);
          const Icon = item.icon;
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                aria-label={item.label}
                className={cn(
                  "group flex h-full flex-col items-center justify-center gap-0.5 text-[11px] font-medium transition-colors",
                  active ? "text-foreground" : "text-muted-foreground",
                )}
              >
                <TabIcon active={active}>
                  <Icon className={cn("size-5", active && "text-primary")} aria-hidden />
                </TabIcon>
                <span className="max-w-full truncate px-1">{item.short ?? item.label}</span>
              </Link>
            </li>
          );
        })}
        <li>
          <Sheet open={open} onOpenChange={setOpen}>
            <SheetTrigger
              className={cn(
                "group flex h-full w-full flex-col items-center justify-center gap-0.5 text-[11px] font-medium",
                moreActive ? "text-foreground" : "text-muted-foreground",
              )}
            >
              <TabIcon active={moreActive}>
                <Ellipsis className={cn("size-5", moreActive && "text-primary")} aria-hidden />
              </TabIcon>
              Mais
            </SheetTrigger>
            <SheetContent side="bottom" className="max-h-[85dvh] rounded-t-2xl pb-safe">
              <SheetHeader className="pb-0">
                <SheetTitle>Menu</SheetTitle>
                <SheetDescription className="sr-only">Todas as áreas da Voryn</SheetDescription>
              </SheetHeader>
              <div className="overflow-y-auto px-4 pb-4">
                {NAV_SECTIONS.map((section) => (
                  <div key={section.label} className="mt-4 first:mt-0">
                    <p className="mb-1 px-2 text-[11px] font-medium tracking-wider text-subtle-foreground uppercase">
                      {section.label}
                    </p>
                    <ul>
                      {section.items.map((item) => {
                        const Icon = item.icon;
                        const active = pathname !== null && isActive(pathname, item.href);
                        return (
                          <li key={item.href}>
                            <Link
                              href={item.href}
                              onClick={() => setOpen(false)}
                              className={cn(
                                "flex h-11 items-center gap-3 rounded-lg px-2 text-sm",
                                active ? "bg-accent text-foreground" : "text-sidebar-foreground",
                              )}
                            >
                              <Icon className={cn("size-[18px]", active ? "text-primary" : "text-muted-foreground")} />
                              <span className="flex-1">{item.label}</span>
                              {!item.available && (
                                <span className="rounded-md border border-border px-1.5 py-px text-[10px] text-subtle-foreground">
                                  Em breve
                                </span>
                              )}
                            </Link>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() => logout.mutate()}
                  disabled={logout.isPending}
                  className="mt-4 flex h-11 w-full items-center gap-3 rounded-lg px-2 text-sm text-muted-foreground"
                >
                  <LogOut className="size-[18px]" /> Sair
                </button>
              </div>
            </SheetContent>
          </Sheet>
        </li>
      </ul>
    </nav>
  );
}

/** Pill behind the icon marks the current tab beyond color; it also gives tap feedback. */
function TabIcon({ active, children }: { active: boolean; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        "flex h-7 w-12 items-center justify-center rounded-full transition-colors duration-150 group-active:bg-accent",
        active && "bg-primary/15",
      )}
    >
      {children}
    </span>
  );
}
