"use client";

import { useMutation } from "@tanstack/react-query";
import { MailCheck } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { api, isApiError } from "@/lib/api/client";
import type { Message } from "@/lib/api/types";

import { AuthHeading, Field, FormError, PasswordStrength, SubmitButton, fieldErrors } from "./form-parts";

export function RegisterForm() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const register = useMutation({
    mutationFn: () =>
      api<Message>("/auth/register", { method: "POST", body: { full_name: fullName, email, password } }),
  });
  const resend = useMutation({
    mutationFn: () => api<Message>("/auth/email/resend", { method: "POST", body: { email } }),
    onSuccess: (data) => toast.success(data.message),
    onError: (error) => toast.error(isApiError(error) ? error.message : "Não foi possível reenviar."),
  });

  if (register.isSuccess) {
    return (
      <div className="text-center">
        <span className="mx-auto mb-6 inline-flex size-12 items-center justify-center rounded-xl border border-border bg-surface">
          <MailCheck className="size-6 text-primary-ink" />
        </span>
        <AuthHeading
          title="Confirme seu e-mail"
          description={
            <>
              Se <span className="text-foreground">{email}</span> puder ser cadastrado, você receberá um link de
              confirmação em instantes. Verifique também a caixa de spam.
            </>
          }
        />
        <p className="text-sm text-muted-foreground">
          Não recebeu?{" "}
          <button type="button" onClick={() => resend.mutate()} disabled={resend.isPending} className="font-medium text-primary-ink hover:underline">
            Reenviar link
          </button>
        </p>
        <p className="mt-8 text-sm">
          <Link href="/entrar" className="text-muted-foreground hover:text-foreground">
            Voltar para o login
          </Link>
        </p>
      </div>
    );
  }

  const errors = fieldErrors(register.error);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    register.mutate();
  };

  return (
    <>
      <AuthHeading title="Criar conta" description="Comece a acompanhar seus investimentos com precisão." />
      <form onSubmit={submit} className="space-y-5" noValidate>
        <FormError error={register.error} />
        <Field label="Nome" autoComplete="name" required value={fullName} onChange={(e) => setFullName(e.target.value)} error={errors.full_name} maxLength={120} />
        <Field
          label="E-mail"
          type="email"
          autoComplete="email"
          inputMode="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={errors.email}
        />
        <Field
          label="Senha"
          type="password"
          autoComplete="new-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={errors.password}
          maxLength={128}
          hint={<PasswordStrength password={password} />}
        />
        <SubmitButton pending={register.isPending}>Criar conta</SubmitButton>
        <p className="text-center text-xs leading-relaxed text-subtle-foreground">
          As análises da Voryn são informativas e não constituem recomendação de investimento.
        </p>
      </form>
      <p className="mt-8 text-center text-sm text-muted-foreground">
        Já tem conta?{" "}
        <Link href="/entrar" className="font-medium text-foreground hover:underline">
          Entrar
        </Link>
      </p>
    </>
  );
}
