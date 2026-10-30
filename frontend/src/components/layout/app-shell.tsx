"use client";

import { cn } from "cn";
import Link from "next/link";
import { Suspense, useEffect, useState, type ReactNode } from "react";

import { NotificationBell } from "@/components/alerts/notification-bell";
import { Logo } from "@/components/brand/logo";

import { MobileNav, MobileNavBar } from "./mobile-nav";
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

export function AppShell({ children }: { children: ReactNode }) {
  const scrolled = useScrolled();
  return (
    <div className="flex min-h-dvh">
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
          <div className="hidden md:block" />
          <div className="flex items-center gap-2">
            <NotificationBell />
            <UserMenu />
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1440px] flex-1 px-4 pt-5 pb-[calc(env(safe-area-inset-bottom)+6.5rem)] md:px-6 md:pt-8 md:pb-10 xl:px-8 *:animate-in *:fade-in-0 *:duration-300">
          {children}
        </main>
      </div>
      <Suspense fallback={<MobileNavBar pathname={null} />}>
        <MobileNav />
      </Suspense>
    </div>
  );
}

