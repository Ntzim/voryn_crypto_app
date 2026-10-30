import { Suspense } from "react";

import { VerifyEmail } from "@/components/auth/password-recovery";

export const metadata = { title: "Confirmar e-mail" };

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <VerifyEmail />
    </Suspense>
  );
}
