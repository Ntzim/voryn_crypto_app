"use client";

import Link from "next/link";
import { Suspense, type ReactNode } from "react";

import { NotificationBell } from "@/components/alerts/notification-bell";
import { Logo } from "@/components/brand/logo";

import { MobileNav } from "./mobile-nav";
import { Sidebar } from "./sidebar";
import { UserMenu } from "./user-menu";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh">
      {/* Navigation reads the pathname (request-time URL data); the fallback reserves its width. */}
      <Suspense fallback={<div className="hidden h-dvh w-[68px] shrink-0 border-r border-sidebar-border bg-sidebar md:block" />}>
        <Sidebar />
      </Suspense>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border bg-background/85 px-4 backdrop-blur-lg md:h-16 md:px-6 xl:px-8">
          <Link href="/dashboard" className="md:hidden" aria-label="Voryn — Dashboard">
            <Logo />
          </Link>
          <div className="hidden md:block" />
          <div className="flex items-center gap-2">
            <NotificationBell />
            <UserMenu />
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1440px] flex-1 px-4 pt-5 pb-28 md:px-6 md:pt-8 md:pb-10 xl:px-8">
          {children}
        </main>
      </div>
      <Suspense>
        <MobileNav />
      </Suspense>
    </div>
  );
}

