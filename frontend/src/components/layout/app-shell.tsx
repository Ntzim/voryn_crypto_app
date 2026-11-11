"use client";

import { cn } from "cn";
import { Search } from "lucide-react";
import Link from "next/link";
import { Suspense, useCallback, useEffect, useState, type ReactNode } from "react";

import { NotificationBell } from "@/components/alerts/notification-bell";
import { Logo } from "@/components/brand/logo";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { ThemeSync, useThemeSetting } from "@/components/theme/use-theme-setting";

import { CommandPalette, useCommandShortcut } from "./command-palette";
import { MobileMenu, MobileNav, MobileNavBar } from "./mobile-nav";
import { SessionPill } from "./session-pill";
import { Sidebar } from "./sidebar";
import { UserMenu } from "./user-menu";

/** True once the page has scrolled under the header (HIG "scroll edge" effect). */
function useScrolled(threshold = 4): boolean {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const update = () => setScrolled(window.scrollY > threshold);
    update();
    window.addEventListener("scroll", update, { passive: true });
    return () => window.removeEventListener("scroll", update);
  }, [threshold]);
  return scrolled;
}

function HeaderThemeToggle() {
  const { theme, setTheme } = useThemeSetting();
  return <ThemeToggle resolved={theme?.resolved} onChange={setTheme} />;
}

export function AppShell({ children }: { children: ReactNode }) {
  const scrolled = useScrolled();
  const [searchOpen, setSearchOpen] = useState(false);
  const openSearch = useCallback(() => setSearchOpen(true), []);
  useCommandShortcut(openSearch);
  return (
    <div className="flex min-h-dvh">
      <ThemeSync />
      {/* Navigation reads the pathname (request-time URL data); the fallback reserves its width. */}
      <Suspense fallback={<div className="hidden h-dvh w-[68px] shrink-0 border-r border-sidebar-border bg-sidebar md:block" />}>
        <Sidebar />
      </Suspense>
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Transparent at the top; glass and a hairline only once content scrolls beneath. */}
        <header
          className={cn(
            "sticky top-0 z-30 flex h-14 items-center justify-between border-b px-4 transition-[background-color,border-color,backdrop-filter] duration-200 md:h-16 md:px-6 xl:px-8",
            scrolled
              ? "border-border bg-background/70 backdrop-blur-xl backdrop-saturate-150"
              : "border-transparent bg-background",
          )}
        >
          <Link href="/dashboard" className="md:hidden" aria-label="Voryn — Dashboard">
            <Logo />
          </Link>
          <button
            type="button"
            onClick={openSearch}
            className="hidden h-10 w-full max-w-[520px] items-center gap-2 rounded-[10px] border border-input/60 bg-surface px-3 text-left text-sm text-subtle-foreground transition-colors hover:border-input md:flex"
          >
            <Search className="size-4 shrink-0" strokeWidth={1.5} aria-hidden />
            <span className="flex-1 truncate">Buscar ativo, FII ou comando</span>
            <kbd className="num rounded-[6px] border border-border px-1.5 py-0.5 text-[11px]">Ctrl K</kbd>
          </button>
          <div className="flex items-center gap-1 md:gap-2">
            <SessionPill className="hidden lg:inline-flex" />
            <button
              type="button"
              onClick={openSearch}
              aria-label="Buscar"
              className="inline-flex size-11 items-center justify-center rounded-[10px] text-muted-foreground hover:text-foreground md:hidden"
            >
              <Search className="size-5" strokeWidth={1.5} />
            </button>
            <HeaderThemeToggle />
            <NotificationBell />
            <UserMenu />
            <Suspense fallback={null}>
              <MobileMenu />
            </Suspense>
          </div>
        </header>
        <CommandPalette open={searchOpen} onOpenChange={setSearchOpen} />
        {/* The one decorative gradient: a faint brand glow at the top of the content. */}
        <main
          className="mx-auto w-full max-w-[1600px] flex-1 px-4 pt-5 pb-[calc(env(safe-area-inset-bottom)+5.5rem)] md:px-6 md:pt-7 md:pb-10 xl:px-8 *:animate-in *:fade-in-0 *:duration-300"
          style={{ backgroundImage: "radial-gradient(900px 260px at 20% -80px, var(--brand-glow), transparent 70%)", backgroundRepeat: "no-repeat" }}
        >
          {children}
        </main>
      </div>
      <Suspense fallback={<MobileNavBar pathname={null} />}>
        <MobileNav />
      </Suspense>
    </div>
  );
}

