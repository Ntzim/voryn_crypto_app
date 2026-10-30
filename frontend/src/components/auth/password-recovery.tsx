"use client";

import { useMutation } from "@tanstack/react-query";
import { CircleCheck, MailCheck, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import type { Message } from "@/lib/api/types";

import { AuthHeading, Field, FormError, PasswordStrength, SubmitButton, fieldErrors } from "./form-parts";

function ResultPanel({
  icon: Icon,
  tone,
  title,
  description,
  action,
}: {
  icon: typeof CircleCheck;
  tone: "primary" | "success" | "destructive";
  title: string;
  description: React.ReactNode;
  action?: React.ReactNode;
}) {
  const color = { primary: "text-primary-ink", success: "text-success", destructive: "text-destructive" }[tone];
  return (
    <div className="text-center">
      <span className="mx-auto mb-6 inline-flex size-12 items-center justify-center rounded-xl border border-border bg-surface">
        <Icon className={`size-6 ${color}`} />
      </span>
      <AuthHeading title={title} description={description} />
      {action}
    </div>
  );
}

export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const request = useMutation({
    mutationFn: () => api<Message>("/auth/password/forgot", { method: "POST", body: { email } }),
  });

  if (request.isSuccess) {
    return (
      <ResultPanel
        icon={MailCheck}
        tone="primary"
        title="Verifique seu e-mail"
        description="Se houver uma conta para este e-mail, enviamos um link para criar uma nova senha. Ele expira em 30 minutos."
        action={
          <Link href="/entrar" className="text-sm text-muted-foreground hover:text-foreground">
            Voltar para o login
          </Link>
        }
      />
    );
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    request.mutate();
  };

  return (
    <>
      <AuthHeading title="Recuperar senha" description="Informe o e-mail da sua conta para receber um link de redefinição." />
      <form onSubmit={submit} className="space-y-5" noValidate>
        <FormError error={request.error} />
        <Field
          label="E-mail"
          type="email"
          autoComplete="email"
          inputMode="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={fieldErrors(request.error).email}
        />
        <SubmitButton pending={request.isPending}>Enviar link</SubmitButton>
      </form>
      <p className="mt-8 text-center text-sm">
        <Link href="/entrar" className="text-muted-foreground hover:text-foreground">
          Voltar para o login
        </Link>
      </p>
    </>
  );
}

export function ResetPasswordForm() {
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [mismatch, setMismatch] = useState(false);
  const reset = useMutation({
    mutationFn: () =>
      api<Message>("/auth/password/reset", { method: "POST", body: { token, new_password: password } }),
  });

  if (!token) {
    return (
      <ResultPanel
        icon={TriangleAlert}
        tone="destructive"
        title="Link inválido"
        description="Este link de redefinição está incompleto. Solicite um novo."
        action={<Button asChild variant="outline"><Link href="/recuperar-senha">Solicitar novo link</Link></Button>}
      />
    );
  }

  if (reset.isSuccess) {
    return (
      <ResultPanel
        icon={CircleCheck}
        tone="success"
        title="Senha redefinida"
        description="Por segurança, todas as sessões abertas foram encerradas. Entre com a nova senha."
        action={<Button asChild size="lg" className="h-11 w-full"><Link href="/entrar">Entrar</Link></Button>}
      />
    );
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (password !== confirm) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    reset.mutate();
  };

  return (
    <>
      <AuthHeading title="Criar nova senha" description="Escolha uma senha que você não use em outros serviços." />
      <form onSubmit={submit} className="space-y-5" noValidate>
        <FormError error={reset.error} />
        <Field
          label="Nova senha"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={fieldErrors(reset.error).new_password}
          hint={<PasswordStrength password={password} />}
          maxLength={128}
        />
        <Field
          label="Confirmar nova senha"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          error={mismatch ? "As senhas não coincidem." : undefined}
          maxLength={128}
        />
        <SubmitButton pending={reset.isPending}>Redefinir senha</SubmitButton>
      </form>
      {reset.isError && (
        <p className="mt-6 text-center text-sm">
          <Link href="/recuperar-senha" className="text-muted-foreground hover:text-foreground">
            Solicitar novo link
          </Link>
        </p>
      )}
    </>
  );
}

export function VerifyEmail() {
  const token = useSearchParams().get("token") ?? "";
  const verify = useMutation({
    mutationFn: () => api<Message>("/auth/email/verify", { method: "POST", body: { token } }),
  });
  const started = useRef(false);

  useEffect(() => {
    // Verification needs JS + an explicit POST, so link scanners can't consume the token.
    if (token && !started.current) {
      started.current = true;
      verify.mutate();
    }
  }, [token, verify]);

  if (!token || verify.isError) {
    return (
      <ResultPanel
        icon={TriangleAlert}
        tone="destructive"
        title="Não foi possível confirmar"
        description="O link é inválido, já foi usado ou expirou. Entre com seu e-mail e senha para receber um novo link."
        action={<Button asChild variant="outline"><Link href="/entrar">Ir para o login</Link></Button>}
      />
    );
  }

  if (verify.isSuccess) {
    return (
      <ResultPanel
        icon={CircleCheck}
        tone="success"
        title="E-mail confirmado"
        description="Sua conta está ativa. Entre para começar."
        action={<Button asChild size="lg" className="h-11 w-full"><Link href="/entrar">Entrar</Link></Button>}
      />
    );
  }

  return <ResultPanel icon={MailCheck} tone="primary" title="Confirmando seu e-mail…" description="Só um instante." />;
}
