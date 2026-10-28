import Link from "next/link";

import { Logo } from "@/components/brand/logo";

export default function AuthLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <aside className="relative hidden overflow-hidden border-r border-border bg-sidebar lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.35]"
          style={{
            backgroundImage:
              "linear-gradient(rgb(148 163 184 / 0.07) 1px, transparent 1px), linear-gradient(90deg, rgb(148 163 184 / 0.07) 1px, transparent 1px)",
            backgroundSize: "48px 48px",
            maskImage: "radial-gradient(ellipse at 30% 40%, black 20%, transparent 75%)",
          }}
        />
        <Link href="/entrar" className="relative">
          <Logo />
        </Link>
        <div className="relative max-w-md">
          <p className="font-heading text-[32px] leading-tight font-semibold text-foreground">
            Intelligence Behind Every Trade.
          </p>
          <p className="mt-4 text-[15px] leading-relaxed text-muted-foreground">
            Acompanhe seu patrimônio, entenda o mercado e avalie oportunidades com dados verificáveis,
            indicadores transparentes e riscos sempre explícitos.
          </p>
        </div>
        <p className="relative text-xs text-subtle-foreground">
          A Voryn não promete lucros. Análises são baseadas em dados e incluem riscos e limitações.
        </p>
      </aside>
      <main className="flex flex-col px-4 py-8 sm:px-8">
        <Link href="/entrar" className="mb-10 lg:hidden">
          <Logo />
        </Link>
        <div className="mx-auto flex w-full max-w-[400px] flex-1 flex-col justify-center pb-10">{children}</div>
      </main>
    </div>
  );
}
