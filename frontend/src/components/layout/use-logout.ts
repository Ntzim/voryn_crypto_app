"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { api } from "@/lib/api/client";

export function useLogout() {
  const queryClient = useQueryClient();
  const router = useRouter();
  return useMutation({
    mutationFn: () => api<void>("/auth/logout", { method: "POST" }),
    onSettled: (_data, error) => {
      // Even if the server call fails, drop all cached user data locally.
      queryClient.clear();
      if (error) toast.error("Não foi possível encerrar a sessão no servidor.");
      router.replace("/entrar");
    },
  });
}
