import Link from "next/link";

import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center px-4 text-center">
      <Logo className="mb-10" />
      <p className="num font-heading text-5xl font-semibold text-foreground">404</p>
      <p className="mt-3 text-sm text-muted-foreground">Esta página não existe ou foi movida.</p>
      <Button asChild className="mt-8">
        <Link href="/dashboard">Ir para o dashboard</Link>
      </Button>
    </main>
  );
}
