"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, apiStream } from "@/lib/api/client";
import type { AIConversation, AIConversationDetail, AIStatus } from "@/lib/api/types";
import { createSseParser } from "@/lib/sse";
import { useHydrationSafe } from "@/lib/use-hydrated";

export function useAiStatus() {
  return useHydrationSafe(
    useQuery({
      queryKey: ["ai", "status"],
      queryFn: ({ signal }) => api<AIStatus>("/ai/status", { signal }),
      staleTime: 60_000,
    }),
  );
}

export function useConversations() {
  return useHydrationSafe(
    useQuery({
      queryKey: ["ai", "conversations"],
      queryFn: ({ signal }) => api<AIConversation[]>("/ai/conversations", { signal }),
    }),
  );
}

export function useConversation(id: string | null) {
  return useHydrationSafe(
    useQuery({
      queryKey: ["ai", "conversation", id],
      queryFn: ({ signal }) => api<AIConversationDetail>(`/ai/conversations/${id}`, { signal }),
      enabled: id !== null,
      retry: false,
    }),
  );
}

export function useConversationMutations() {
  const queryClient = useQueryClient();
  return {
    create: useMutation({
      mutationFn: () => api<AIConversation>("/ai/conversations", { method: "POST" }),
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: ["ai", "conversations"] });
      },
    }),
    remove: useMutation({
      mutationFn: (id: string) => api<void>(`/ai/conversations/${id}`, { method: "DELETE" }),
      onSuccess: (_data, id) => {
        queryClient.removeQueries({ queryKey: ["ai", "conversation", id] });
        void queryClient.invalidateQueries({ queryKey: ["ai", "conversations"] });
      },
    }),
  };
}

export type ReplyEvent =
  | { type: "status"; text: string }
  | { type: "delta"; text: string }
  | { type: "notice"; text: string }
  | { type: "error"; text: string; retryable: boolean }
  | { type: "done"; sources: string[] };

/** Send a message and dispatch the streamed reply; resolves when the stream closes. */
export async function streamReply(
  conversationId: string,
  content: string,
  onEvent: (event: ReplyEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const stream = await apiStream(`/ai/conversations/${conversationId}/messages`, { content }, signal);
  const feed = createSseParser(({ event, data }) => {
    const payload = data as Record<string, unknown>;
    switch (event) {
      case "status":
      case "delta":
      case "notice":
        onEvent({ type: event, text: String(payload.text ?? "") });
        break;
      case "error":
        onEvent({ type: "error", text: String(payload.text ?? ""), retryable: payload.retryable === true });
        break;
      case "done":
        onEvent({ type: "done", sources: (payload.sources as string[] | undefined) ?? [] });
        break;
    }
  });
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    feed(decoder.decode(value, { stream: true }));
  }
  feed(decoder.decode());
}
