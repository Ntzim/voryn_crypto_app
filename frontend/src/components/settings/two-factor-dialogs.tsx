"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Download, LoaderCircle } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Field, FormError } from "@/components/auth/form-parts";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { InputOTP, InputOTPGroup, InputOTPSlot } from "@/components/ui/input-otp";
import { api } from "@/lib/api/client";
import type { MfaSetup, RecoveryCodes, User } from "@/lib/api/types";
import { queryKeys } from "@/lib/queries";

function useMarkMfa() {
  const queryClient = useQueryClient();
  return (enabled: boolean) =>
    queryClient.setQueryData<User>(queryKeys.me, (u) => (u ? { ...u, mfa_enabled: enabled } : u));
}

type DialogProps = { open: boolean; onOpenChange: (o: boolean) => void };

export function TwoFactorSetupDialog({ open, onOpenChange }: DialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* Content mounts per opening: fresh secret and state every time. */}
      {open && <SetupContent onOpenChange={onOpenChange} />}
    </Dialog>
  );
}

function SetupContent({ onOpenChange }: Pick<DialogProps, "onOpenChange">) {
  const markMfa = useMarkMfa();
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [saved, setSaved] = useState(false);

  // The password is confirmed first so a stolen session cannot enrol another authenticator.
  const setup = useMutation({
    mutationFn: () => api<MfaSetup>("/me/mfa/setup", { method: "POST", body: { password } }),
    onSuccess: () => setPassword(""),
  });
  const enable = useMutation({
    mutationFn: (value: string) => api<RecoveryCodes>("/me/mfa/enable", { method: "POST", body: { code: value } }),
    onSuccess: (data) => {
      setCodes(data.recovery_codes);
      markMfa(true);
    },
    onError: () => setCode(""),
  });

  const confirmPassword = (event: FormEvent) => {
    event.preventDefault();
    setup.mutate();
  };

  // Recovery codes are shown once; don't let an accidental outside click dismiss them.
  const blockDismiss = (event: Event) => {
    if (codes && !saved) event.preventDefault();
  };

  return (
    <DialogContent
      className="sm:max-w-md"
      onInteractOutside={blockDismiss}
      onEscapeKeyDown={blockDismiss}
      showCloseButton={!codes || saved}
    >
        {codes ? (
          <RecoveryCodesStep codes={codes} saved={saved} onSavedChange={setSaved} onDone={() => onOpenChange(false)} />
        ) : !setup.data ? (
          <>
            <DialogHeader>
              <DialogTitle>Ativar autenticação em dois fatores</DialogTitle>
              <DialogDescription>Confirme sua senha para continuar.</DialogDescription>
            </DialogHeader>
            <form onSubmit={confirmPassword} className="space-y-4" noValidate>
              <FormError error={setup.error} />
              <Field
                label="Senha"
                type="password"
                autoComplete="current-password"
                autoFocus
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <DialogFooter>
                <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
                  Cancelar
                </Button>
                <Button type="submit" disabled={setup.isPending || !password}>
                  {setup.isPending && <LoaderCircle className="animate-spin" />} Continuar
                </Button>
              </DialogFooter>
            </form>
          </>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>Ativar autenticação em dois fatores</DialogTitle>
              <DialogDescription>
                Escaneie o QR code com seu aplicativo autenticador e digite o código gerado.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col items-center gap-4">
              {/* The secret expires server-side after 10 minutes. */}
              <div className="rounded-xl bg-white p-3">
                <QRCodeSVG value={setup.data.otpauth_uri} size={168} level="M" />
              </div>
              <details className="w-full text-center text-xs text-muted-foreground">
                <summary className="cursor-pointer hover:text-foreground">Não consegue escanear? Digite a chave</summary>
                <code className="mt-2 block rounded-md bg-surface px-3 py-2 font-mono text-[13px] tracking-wider break-all text-foreground select-all">
                  {setup.data.secret}
                </code>
              </details>
              <FormError error={enable.error} />
              <InputOTP
                maxLength={6}
                value={code}
                onChange={(value) => {
                  setCode(value);
                  if (value.length === 6) enable.mutate(value);
                }}
                disabled={enable.isPending}
                inputMode="numeric"
                pattern="^[0-9]*$"
                aria-label="Código de 6 dígitos"
              >
                <InputOTPGroup>
                  {Array.from({ length: 6 }, (_, i) => (
                    <InputOTPSlot key={i} index={i} className="size-11 text-base" />
                  ))}
                </InputOTPGroup>
              </InputOTP>
              {enable.isPending && <LoaderCircle className="size-4 animate-spin text-muted-foreground" />}
            </div>
          </>
        )}
    </DialogContent>
  );
}

function RecoveryCodesStep({
  codes,
  saved,
  onSavedChange,
  onDone,
}: {
  codes: string[];
  saved: boolean;
  onSavedChange: (v: boolean) => void;
  onDone: () => void;
}) {
  const text = codes.join("\n");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Códigos copiados.");
    } catch {
      toast.error("Não foi possível copiar. Selecione e copie manualmente.");
    }
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([`Códigos de recuperação Voryn\n\n${text}\n`], { type: "text/plain" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: "voryn-codigos-de-recuperacao.txt" });
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <DialogHeader>
        <DialogTitle>Guarde seus códigos de recuperação</DialogTitle>
        <DialogDescription>
          Cada código funciona uma única vez, caso você perca acesso ao aplicativo autenticador. Eles não serão exibidos novamente.
        </DialogDescription>
      </DialogHeader>
      <ul className="num grid grid-cols-2 gap-2 rounded-lg border border-border bg-surface p-4 font-mono text-sm text-foreground">
        {codes.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={copy}>
          <Copy /> Copiar
        </Button>
        <Button variant="outline" size="sm" onClick={download}>
          <Download /> Baixar .txt
        </Button>
      </div>
      <label className="flex items-center gap-2 text-sm text-muted-foreground">
        <input type="checkbox" checked={saved} onChange={(e) => onSavedChange(e.target.checked)} className="size-4 accent-primary" />
        Guardei os códigos em um local seguro
      </label>
      <DialogFooter>
        <Button onClick={onDone} disabled={!saved}>
          <Check /> Concluir
        </Button>
      </DialogFooter>
    </>
  );
}

export function TwoFactorDisableDialog({ open, onOpenChange }: DialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {open && <DisableContent onOpenChange={onOpenChange} />}
    </Dialog>
  );
}

function DisableContent({ onOpenChange }: Pick<DialogProps, "onOpenChange">) {
  const markMfa = useMarkMfa();
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const disable = useMutation({
    mutationFn: () => api<void>("/me/mfa/disable", { method: "POST", body: { password, code } }),
    onSuccess: () => {
      markMfa(false);
      toast.success("Autenticação em dois fatores desativada.");
      onOpenChange(false);
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    disable.mutate();
  };

  return (
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Desativar autenticação em dois fatores</DialogTitle>
          <DialogDescription>Sua conta ficará protegida apenas pela senha. Confirme sua identidade para continuar.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4" noValidate>
          <FormError error={disable.error} />
          <Field label="Senha" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <Field
            label="Código do autenticador ou de recuperação"
            autoComplete="one-time-code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancelar
            </Button>
            <Button type="submit" variant="destructive" disabled={disable.isPending || !password || code.length < 6}>
              Desativar
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
  );
}
