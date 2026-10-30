import { Suspense } from "react";

import { ResetPasswordForm } from "@/components/auth/password-recovery";

export const metadata = { title: "Redefinir senha" };

export default function ResetPasswordPage() {
  return (
    <Suspense>
      <ResetPasswordForm />
    </Suspense>
  );
}
