"use client";

import { cn } from "cn";
import { LogOut, Menu } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

import { MOBILE_ITEMS, isActive } from "./nav-config";
import { useLogout } from "./use-logout";
import { useNavSections } from "./use-nav-sections";

/** Bottom navigation for phones: five thumb-reachable areas. */
export function MobileNav() {
  return <MobileNavBar pathname={usePathname()} />;
}

/**
 * The bar itself. Reading the URL suspends, so the app shell renders this with
 * `pathname={null}` as the Suspense fallback: the bar is in the first HTML instead of
 * appearing only once the JavaScript has loaded.
 */
export function MobileNavBar({ pathname }: { pathname: string | null }) {
  return (
    <nav aria-label="Navegação principal" className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-bar pb-safe md:hidden">
      <ul className="mx-auto grid h-16 max-w-md grid-cols-5">
        {MOBILE_ITEMS.map((item) => {
          const active = pathname !== null && isActive(pathname, item);
          const Icon = item.icon;
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex h-full flex-col items-center justify-center gap-1 text-[11px] font-medium transition-colors",
                  active ? "text-primary-ink" : "text-muted-foreground",
                )}
              >
                <Icon className="size-5" strokeWidth={1.5} aria-hidden />
                <span className="max-w-full truncate px-1">{item.short ?? item.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** Every area, for phones (the bottom bar only has room for five): opened from the header. */
export function MobileMenu() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const logout = useLogout();
  const sections = useNavSections();
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger className="inline-flex size-11 items-center justify-center rounded-[10px] text-muted-foreground hover:text-foreground md:hidden" aria-label="Abrir menu">
        <Menu className="size-5" strokeWidth={1.5} />
      </SheetTrigger>
      <SheetContent side="bottom" className="max-h-[85dvh] rounded-t-2xl pb-safe">
        <SheetHeader className="pb-0">
          <SheetTitle>Menu</SheetTitle>
          <SheetDescription className="sr-only">Todas as áreas da Voryn</SheetDescription>
        </SheetHeader>
        <div className="overflow-y-auto px-4 pb-4">
          {sections.map((section) => (
            <div key={section.label} className="mt-4 first:mt-0">
              <p className="overline mb-1 px-2 text-subtle-foreground">{section.label}</p>
              <ul>
                {section.items.map((item) => {
                  const Icon = item.icon;
                  const active = isActive(pathname, item);
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        onClick={() => setOpen(false)}
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "flex h-11 items-center gap-3 rounded-[10px] px-2 text-sm",
                          active ? "bg-brand-soft font-semibold text-primary-ink" : "text-sidebar-foreground",
                        )}
                      >
                        <Icon className="size-5" strokeWidth={1.5} />
                        <span className="flex-1">{item.label}</span>
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
            className="mt-4 flex h-11 w-full items-center gap-3 rounded-[10px] px-2 text-sm text-muted-foreground"
          >
            <LogOut className="size-5" strokeWidth={1.5} /> Sair
          </button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
