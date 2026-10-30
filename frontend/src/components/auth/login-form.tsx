"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MailCheck } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { InputOTP, InputOTPGroup, InputOTPSlot } from "@/components/ui/input-otp";
import { Label } from "@/components/ui/label";
import { api, isApiError } from "@/lib/api/client";
import type { LoginResponse, Message } from "@/lib/api/types";
import { queryKeys } from "@/lib/queries";
import { safeNext } from "@/lib/safe-next";

import { AuthHeading, Field, FormError, SubmitButton, fieldErrors } from "./form-parts";


export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);

  const finish = (data: LoginResponse) => {
    if (data.user) queryClient.setQueryData(queryKeys.me, data.user);
    router.replace(safeNext(params.get("next")));
  };

  const login = useMutation({
    mutationFn: () => api<LoginResponse>("/auth/login", { method: "POST", body: { email, password } }),
    onSuccess: (data) => {
      if (data.status === "mfa_required" && data.mfa_token) setMfaToken(data.mfa_token);
      else finish(data);
    },
  });

  const resend = useMutation({
    mutationFn: () => api<Message>("/auth/email/resend", { method: "POST", body: { email } }),
    onSuccess: (data) => toast.success(data.message),
    onError: (error) => toast.error(isApiError(error) ? error.message : "Não foi possível reenviar."),
  });

  if (mfaToken) {
    return <MfaStep mfaToken={mfaToken} onDone={finish} onRestart={() => { setMfaToken(null); setPassword(""); }} />;
  }

  const errors = fieldErrors(login.error);
  const unverified = isApiError(login.error, "email_not_verified");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    login.mutate();
  };

  return (
    <>
      <AuthHeading title="Entrar na Voryn" description="Acesse sua central de inteligência cripto." />
      <form onSubmit={submit} className="space-y-5" noValidate>
        {unverified ? (
          <Alert className="border-warning/30 bg-warning/10">
            <MailCheck className="text-warning" />
            <AlertDescription className="text-foreground">
              Confirme seu e-mail para entrar.{" "}
              <button type="button" onClick={() => resend.mutate()} disabled={resend.isPending} className="font-medium text-primary hover:underline">
                Reenviar link
              </button>
            </AlertDescription>
          </Alert>
        ) : (
          <FormError error={login.error} />
        )}
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
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={errors.password}
          labelAside={
            <Link href="/recuperar-senha" className="text-xs text-muted-foreground hover:text-foreground">
              Esqueceu a senha?
            </Link>
          }
        />
        <SubmitButton pending={login.isPending}>Entrar</SubmitButton>
      </form>
      <p className="mt-8 text-center text-sm text-muted-foreground">
        Ainda não tem conta?{" "}
        <Link href="/criar-conta" className="font-medium text-foreground hover:underline">
          Criar conta
        </Link>
      </p>
    </>
  );
}

function MfaStep({
  mfaToken,
  onDone,
  onRestart,
}: {
  mfaToken: string;
  onDone: (data: LoginResponse) => void;
  onRestart: () => void;
}) {
  const [code, setCode] = useState("");
  const [useRecovery, setUseRecovery] = useState(false);
  const verify = useMutation({
    mutationFn: (value: string) =>
      api<LoginResponse>("/auth/login/mfa", { method: "POST", body: { mfa_token: mfaToken, code: value } }),
    onSuccess: onDone,
    onError: () => setCode(""),
  });
  const expired = isApiError(verify.error, "mfa_challenge_expired") || isApiError(verify.error, "rate_limited");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (code) verify.mutate(code);
  };

  return (
    <>
      <AuthHeading
        title="Verificação em duas etapas"
        description={
          useRecovery
            ? "Digite um dos códigos de recuperação que você guardou ao ativar o 2FA."
            : "Digite o código de 6 dígitos do seu aplicativo autenticador."
        }
      />
      <form onSubmit={submit} className="space-y-5">
        <FormError error={verify.error} />
        {useRecovery ? (
          <Field
            label="Código de recuperação"
            autoComplete="one-time-code"
            placeholder="xxxxx-xxxxx"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            autoFocus
          />
        ) : (
          <div className="space-y-2">
            <Label className="sr-only" htmlFor="totp">Código</Label>
            <InputOTP
              id="totp"
              maxLength={6}
              value={code}
              onChange={(value) => {
                setCode(value);
                if (value.length === 6) verify.mutate(value);
              }}
              autoFocus
              inputMode="numeric"
              pattern="^[0-9]*$"
              containerClassName="justify-center"
            >
              <InputOTPGroup>
                {Array.from({ length: 6 }, (_, i) => (
                  <InputOTPSlot key={i} index={i} className="size-12 text-lg" />
                ))}
              </InputOTPGroup>
            </InputOTP>
          </div>
        )}
        {expired ? (
          <Button type="button" variant="outline" size="lg" className="h-11 w-full" onClick={onRestart}>
            Entrar novamente
          </Button>
        ) : (
          <SubmitButton pending={verify.isPending}>Verificar</SubmitButton>
        )}
      </form>
      <div className="mt-6 flex justify-between text-sm">
        <button type="button" onClick={() => { setUseRecovery((v) => !v); setCode(""); }} className="text-muted-foreground hover:text-foreground">
          {useRecovery ? "Usar aplicativo autenticador" : "Usar código de recuperação"}
        </button>
        <button type="button" onClick={onRestart} className="text-muted-foreground hover:text-foreground">
          Voltar
        </button>
      </div>
    </>
  );
}
