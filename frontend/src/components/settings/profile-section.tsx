"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Field, FormError, fieldErrors } from "@/components/auth/form-parts";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/client";
import type { User } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { queryKeys, useMe, usePreferences } from "@/lib/queries";

import { SettingsSection } from "./section";

export function ProfileSection() {
  const { data: user } = useMe();
  if (!user) return <Skeleton className="h-56 rounded-xl" />;
  // Keyed so the form re-initializes if the profile changes elsewhere (e.g. another tab).
  return <ProfileForm key={user.full_name} user={user} />;
}

function ProfileForm({ user }: { user: User }) {
  const { locale, timeZone } = usePreferences();
  const queryClient = useQueryClient();
  const [name, setName] = useState(user.full_name);

  const save = useMutation({
    mutationFn: () => api<User>("/me", { method: "PATCH", body: { full_name: name } }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.me, updated);
      toast.success("Perfil atualizado.");
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };

  return (
    <SettingsSection
      title="Informações pessoais"
      description={`Membro desde ${formatDateTime(user.created_at, locale, timeZone, { dateStyle: "long" })}.`}
    >
      <form onSubmit={submit} className="max-w-md space-y-5">
        <FormError error={save.error} />
        <Field label="Nome" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} autoComplete="name" error={fieldErrors(save.error).full_name} />
        <Field
          label="E-mail"
          value={user.email}
          readOnly
          disabled
          hint={
            <span className="inline-flex items-center gap-1.5">
              <CircleCheck className="size-3.5 text-success" /> Verificado. A troca de e-mail estará disponível em breve.
            </span>
          }
        />
        <Button type="submit" disabled={save.isPending || name.trim() === user.full_name}>
          Salvar alterações
        </Button>
      </form>
    </SettingsSection>
  );
}
