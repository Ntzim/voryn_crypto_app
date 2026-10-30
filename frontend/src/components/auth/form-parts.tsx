"use client";

import { cn } from "cn";
import { Eye, EyeOff, LoaderCircle, TriangleAlert } from "lucide-react";
import { useId, useState, type ComponentProps, type ReactNode } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api/client";

export function AuthHeading({ title, description }: { title: string; description?: ReactNode }) {
  return (
    <div className="mb-8">
      <h1 className="text-2xl font-semibold text-foreground">{title}</h1>
      {description && <p className="mt-2 text-sm text-muted-foreground">{description}</p>}
    </div>
  );
}

type FieldProps = ComponentProps<typeof Input> & {
  label: string;
  error?: string;
  hint?: ReactNode;
  labelAside?: ReactNode;
};

export function Field({ label, error, hint, labelAside, className, type, ...props }: FieldProps) {
  const id = useId();
  const [visible, setVisible] = useState(false);
  const isPassword = type === "password";
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label htmlFor={id}>{label}</Label>
        {labelAside}
      </div>
      <div className="relative">
        <Input
          id={id}
          type={isPassword && visible ? "text" : type}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
          className={cn("h-11 bg-surface", isPassword && "pr-11", className)}
          {...props}
        />
        {isPassword && (
          <button
            type="button"
            onClick={() => setVisible((v) => !v)}
            className="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-subtle-foreground hover:text-foreground"
            aria-label={visible ? "Ocultar senha" : "Mostrar senha"}
          >
            {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </button>
        )}
      </div>
      {error ? (
        <p id={`${id}-error`} className="text-xs text-destructive">
          {error}
        </p>
      ) : (
        hint && (
          <div id={`${id}-hint`} className="text-xs text-muted-foreground">
            {hint}
          </div>
        )
      )}
    </div>
  );
}

export function SubmitButton({ pending, children }: { pending: boolean; children: ReactNode }) {
  return (
    <Button type="submit" size="lg" className="h-11 w-full text-sm" disabled={pending}>
      {pending && <LoaderCircle className="animate-spin" />}
      {children}
    </Button>
  );
}

export function FormError({ error }: { error: unknown }) {
  if (!error) return null;
  // Field-level validation errors are shown next to their inputs.
  if (error instanceof ApiError && error.code === "validation_error") return null;
  const message = error instanceof ApiError ? error.message : "Algo deu errado. Tente novamente.";
  return (
    <Alert variant="destructive" className="border-destructive/30 bg-destructive/10">
      <TriangleAlert />
      <AlertDescription className="text-destructive">{message}</AlertDescription>
    </Alert>
  );
}

export function fieldErrors(error: unknown): Record<string, string> {
  return error instanceof ApiError ? error.fieldErrors : {};
}

/** Lightweight strength cue: rewards length, the factor that matters most. */
export function PasswordStrength({ password }: { password: string }) {
  if (!password) return <span>Use pelo menos 10 caracteres. Frases longas são mais seguras.</span>;
  const variety = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(password)).length;
  const score = password.length < 10 ? 0 : password.length >= 16 || variety >= 3 ? 2 : 1;
  const labels = ["Muito curta", "Razoável", "Forte"];
  const colors = ["bg-destructive", "bg-warning", "bg-success"];
  return (
    <span className="flex items-center gap-2">
      <span className="flex flex-1 gap-1" aria-hidden>
        {[0, 1, 2].map((i) => (
          <span key={i} className={cn("h-1 flex-1 rounded-full", i <= score ? colors[score] : "bg-accent")} />
        ))}
      </span>
      <span className="w-20 text-right">{labels[score]}</span>
    </span>
  );
}
