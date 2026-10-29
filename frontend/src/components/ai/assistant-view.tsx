"use client";

import { useQueryClient } from "@tanstack/react-query";
import { cn } from "cn";
import {
  ArrowUp,
  Database,
  History,
  Loader2,
  MessageSquarePlus,
  RotateCcw,
  Sparkles,
  Square,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";

import { PageHeader } from "@/components/common/page-header";
import { EmptyState, ErrorState } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import {
  streamReply,
  useAiStatus,
  useConversation,
  useConversationMutations,
  useConversations,
} from "@/lib/ai-queries";
import { ApiError } from "@/lib/api/client";
import type { AIConversation, AIMessage } from "@/lib/api/types";
import { formatDateTime, formatRelative } from "@/lib/format";
import { usePreferences } from "@/lib/queries";

import { MarkdownText } from "./markdown";

const MAX_LENGTH = 4000;

const SUGGESTIONS = [
  "Como está minha carteira hoje?",
  "Qual foi minha melhor operação?",
  "O que os indicadores dizem sobre o Bitcoin no diário?",
  "Quais ativos têm os maiores scores de oportunidade agora?",
];

/** The reply being streamed right now. */
type Live = { question: string; answer: string; status: string | null };
/** Shown after the last question when no answer was stored (error, notice or interruption). */
type Trailing = { kind: "error" | "notice"; text: string; retry?: string };

export function AssistantView() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const activeId = params.get("c");

  const status = useAiStatus();
  const conversations = useConversations();
  const conversation = useConversation(activeId);
  const { create, remove } = useConversationMutations();

  const [live, setLive] = useState<Live | null>(null);
  const [trailing, setTrailing] = useState<Trailing | null>(null);
  const [listOpen, setListOpen] = useState(false);
  const [toDelete, setToDelete] = useState<AIConversation | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const setActive = (id: string | null) => {
    router.replace(id ? `${pathname}?c=${id}` : pathname, { scroll: false });
  };
  const open = (id: string | null) => {
    if (live) return;
    setTrailing(null);
    setListOpen(false);
    setActive(id);
  };

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || live) return;
    setTrailing(null);
    setLive({ question, answer: "", status: null });
    const controller = new AbortController();
    abortRef.current = controller;
    const outcome: { trailing: Trailing | null } = { trailing: null };
    let id = activeId;
    try {
      if (!id) {
        id = (await create.mutateAsync()).id;
        setActive(id);
      }
      await streamReply(
        id,
        question,
        (event) => {
          if (event.type === "status") setLive((l) => l && { ...l, status: event.text });
          else if (event.type === "delta") setLive((l) => l && { ...l, answer: l.answer + event.text, status: null });
          else if (event.type === "notice") outcome.trailing = { kind: "notice", text: event.text };
          else if (event.type === "error")
            outcome.trailing = { kind: "error", text: event.text, retry: event.retryable ? question : undefined };
        },
        controller.signal,
      );
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        outcome.trailing = { kind: "notice", text: "Resposta interrompida." };
      } else {
        const retryable = !(error instanceof ApiError) || error.status === 0 || error.status >= 500;
        outcome.trailing = {
          kind: "error",
          text: error instanceof ApiError ? error.message : "Não foi possível obter a resposta.",
          retry: retryable ? question : undefined,
        };
      }
    } finally {
      abortRef.current = null;
      await Promise.all([
        id ? queryClient.invalidateQueries({ queryKey: ["ai", "conversation", id] }) : null,
        queryClient.invalidateQueries({ queryKey: ["ai", "conversations"] }),
        queryClient.invalidateQueries({ queryKey: ["ai", "status"] }),
      ]);
      setTrailing(outcome.trailing);
      setLive(null);
    }
  };

  const confirmDelete = async () => {
    if (!toDelete) return;
    await remove.mutateAsync(toDelete.id);
    if (toDelete.id === activeId) open(null);
    setToDelete(null);
  };

  const list = (
    <ConversationList
      items={conversations.data}
      isPending={conversations.isPending}
      activeId={activeId}
      disabled={live !== null}
      onSelect={open}
      onDelete={setToDelete}
    />
  );

  const enabled = status.data?.enabled;

  return (
    <>
      <PageHeader
        title="Voryn AI"
        description="Pergunte sobre sua carteira e o mercado. As respostas usam apenas os dados calculados pela plataforma."
        actions={
          <>
            <Button variant="outline" className="lg:hidden" onClick={() => setListOpen(true)}>
              <History /> Conversas
            </Button>
            <Button variant="outline" disabled={live !== null || !activeId} onClick={() => open(null)}>
              <MessageSquarePlus /> Nova conversa
            </Button>
          </>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="hidden lg:block" aria-label="Conversas">
          {list}
        </aside>

        {status.isPending ? (
          <Skeleton className="h-[480px] rounded-xl" />
        ) : status.isError ? (
          <Card>
            <ErrorState error={status.error} onRetry={() => void status.refetch()} />
          </Card>
        ) : !enabled ? (
          <Card>
            <EmptyState
              icon={Sparkles}
              title="Voryn AI indisponível neste ambiente"
              description={
                <>
                  O assistente ainda não foi configurado. Carteira, mercado, análises e sinais continuam
                  funcionando normalmente.
                  <span className="mt-2 block text-xs">Administradores: defina ANTHROPIC_API_KEY no backend.</span>
                </>
              }
            />
          </Card>
        ) : (
          <ChatPanel
            key={activeId ?? "new"}
            messages={activeId ? conversation.data?.messages : []}
            loading={activeId !== null && conversation.isPending && !live}
            error={activeId && conversation.isError ? conversation.error : null}
            canContinue={conversation.data?.can_continue ?? true}
            live={live}
            trailing={trailing}
            onSend={send}
            onStop={() => abortRef.current?.abort()}
            perHour={status.data?.messages_per_hour}
          />
        )}
      </div>

      <Sheet open={listOpen} onOpenChange={setListOpen}>
        <SheetContent side="left" className="w-[300px] p-4">
          <SheetHeader className="p-0">
            <SheetTitle>Conversas</SheetTitle>
          </SheetHeader>
          {list}
        </SheetContent>
      </Sheet>

      <Dialog open={toDelete !== null} onOpenChange={(o) => !o && setToDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Excluir conversa?</DialogTitle>
            <DialogDescription>
              “{toDelete?.title}” e todas as suas mensagens serão removidas permanentemente.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setToDelete(null)}>
              Cancelar
            </Button>
            <Button variant="destructive" disabled={remove.isPending} onClick={() => void confirmDelete()}>
              Excluir
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function ConversationList({
  items,
  isPending,
  activeId,
  disabled,
  onSelect,
  onDelete,
}: {
  items: AIConversation[] | undefined;
  isPending: boolean;
  activeId: string | null;
  disabled: boolean;
  onSelect: (id: string) => void;
  onDelete: (conversation: AIConversation) => void;
}) {
  const { locale } = usePreferences();
  if (isPending) {
    return (
      <div className="space-y-2">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-12 rounded-lg" />
        ))}
      </div>
    );
  }
  if (!items?.length) {
    return <p className="px-1 py-2 text-sm text-muted-foreground">Suas conversas aparecem aqui.</p>;
  }
  return (
    <ul className="space-y-1">
      {items.map((c) => (
        <li key={c.id} className="group relative">
          <button
            type="button"
            disabled={disabled}
            aria-current={c.id === activeId ? "page" : undefined}
            onClick={() => onSelect(c.id)}
            className={cn(
              "w-full rounded-lg px-3 py-2 pr-9 text-left transition-colors hover:bg-surface disabled:opacity-60",
              c.id === activeId && "bg-surface ring-1 ring-border",
            )}
          >
            <span className="block truncate text-sm text-foreground">{c.title}</span>
            <span className="block text-xs text-muted-foreground">{formatRelative(c.updated_at, locale)}</span>
          </button>
          <Button
            variant="ghost"
            size="icon-sm"
            disabled={disabled}
            aria-label={`Excluir “${c.title}”`}
            onClick={() => onDelete(c)}
            className="absolute top-1/2 right-1 -translate-y-1/2 text-muted-foreground opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
          >
            <Trash2 />
          </Button>
        </li>
      ))}
    </ul>
  );
}

function ChatPanel({
  messages,
  loading,
  error,
  canContinue,
  live,
  trailing,
  onSend,
  onStop,
  perHour,
}: {
  messages: AIMessage[] | undefined;
  loading: boolean;
  error: unknown;
  canContinue: boolean;
  live: Live | null;
  trailing: Trailing | null;
  onSend: (text: string) => Promise<void>;
  onStop: () => void;
  perHour: number | undefined;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const stored = messages ?? [];
  const last = stored.at(-1);
  // A refetch during streaming may already include the question being answered.
  const shown = live && last?.role === "user" && last.text === live.question ? stored.slice(0, -1) : stored;
  const unanswered = shown.at(-1)?.role !== "assistant";
  const empty = !loading && shown.length === 0 && !live && !trailing;

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el && stickRef.current && !empty) el.scrollTop = el.scrollHeight;
  }, [empty, shown.length, live?.answer, live?.status, trailing]);

  const send = (text: string) => {
    stickRef.current = true;
    void onSend(text);
  };

  return (
    <Card className="flex h-[calc(100dvh-22rem)] min-h-[420px] flex-col gap-0 py-0 md:h-[calc(100dvh-14rem)] md:min-h-[460px]">
      <div
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        }}
        className="flex-1 overflow-y-auto px-4 py-5 md:px-6"
      >
        {error ? (
          <ErrorState error={error} />
        ) : loading ? (
          <div className="space-y-4">
            <Skeleton className="ml-auto h-10 w-2/3 rounded-2xl" />
            <Skeleton className="h-32 w-full rounded-xl" />
          </div>
        ) : empty ? (
          <Welcome onPick={send} />
        ) : (
          <div className="mx-auto flex max-w-3xl flex-col gap-6" aria-live="polite">
            {shown.map((m) =>
              m.role === "user" ? (
                <UserBubble key={m.id} text={m.text} />
              ) : (
                <AssistantBubble key={m.id} text={m.text} sources={m.sources} createdAt={m.created_at} />
              ),
            )}
            {live && (
              <>
                <UserBubble text={live.question} />
                <AssistantBubble text={live.answer} status={live.status} streaming />
              </>
            )}
            {!live && trailing && unanswered && (
              <TrailingNote trailing={trailing} onRetry={trailing.retry ? () => send(trailing.retry ?? "") : undefined} />
            )}
          </div>
        )}
      </div>
      <Composer
        disabled={!canContinue || Boolean(error)}
        busy={live !== null}
        onSend={send}
        onStop={onStop}
        hint={
          canContinue
            ? undefined
            : "Esta conversa atingiu o limite de mensagens. Inicie uma nova conversa para continuar."
        }
        perHour={perHour}
      />
    </Card>
  );
}

function Welcome({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center py-8 text-center">
      <span className="mb-4 inline-flex size-12 items-center justify-center rounded-2xl border border-primary/30 bg-primary/10">
        <Sparkles className="size-5 text-primary" aria-hidden />
      </span>
      <h2 className="font-heading text-lg font-semibold text-foreground">Como posso ajudar?</h2>
      <p className="mt-1.5 text-sm text-muted-foreground">
        Respostas baseadas nos motores da Voryn, separando dados observados, interpretações, hipóteses e
        riscos, sempre com o período e o horário dos dados.
      </p>
      <div className="mt-6 grid w-full gap-2 sm:grid-cols-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onPick(s)}
            className="rounded-xl border border-border bg-surface px-4 py-3 text-left text-sm text-foreground/90 transition-colors hover:border-primary/40 hover:bg-primary/5"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-2xl rounded-br-md border border-primary/25 bg-primary/10 px-4 py-2.5 text-sm whitespace-pre-wrap text-foreground">
        {text}
      </div>
    </div>
  );
}

function AssistantBubble({
  text,
  sources = [],
  createdAt,
  status,
  streaming = false,
}: {
  text: string;
  sources?: string[];
  createdAt?: string;
  status?: string | null;
  streaming?: boolean;
}) {
  const { locale, timeZone } = usePreferences();
  return (
    <div className="flex gap-3">
      <span className="mt-0.5 inline-flex size-7 shrink-0 items-center justify-center rounded-lg border border-primary/30 bg-primary/10">
        <Sparkles className="size-3.5 text-primary" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        {streaming && !text && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
            {status ?? "Pensando…"}
          </p>
        )}
        {text && <MarkdownText text={text} />}
        {streaming && text && status && (
          <p className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" aria-hidden />
            {status}
          </p>
        )}
        {!streaming && (sources.length > 0 || createdAt) && (
          <div className="mt-3 flex flex-col gap-2 text-xs text-muted-foreground">
            {sources.length > 0 && (
              <details className="group rounded-lg border border-border bg-surface/60 px-3 py-2">
                <summary className="flex cursor-pointer list-none items-center gap-1.5 select-none">
                  <Database className="size-3.5" aria-hidden />
                  Dados consultados ({sources.length})
                </summary>
                <ul className="mt-2 space-y-1">
                  {sources.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
              </details>
            )}
            {createdAt && <span>{formatDateTime(createdAt, locale, timeZone)}</span>}
          </div>
        )}
      </div>
    </div>
  );
}

function TrailingNote({ trailing, onRetry }: { trailing: Trailing; onRetry?: () => void }) {
  const isError = trailing.kind === "error";
  return (
    <div
      role={isError ? "alert" : "status"}
      className={cn(
        "flex flex-col gap-3 rounded-xl border px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between",
        isError ? "border-destructive/30 bg-destructive/5" : "border-border bg-surface",
      )}
    >
      <p className="flex items-start gap-2">
        <TriangleAlert className={cn("mt-0.5 size-4 shrink-0", isError ? "text-destructive" : "text-warning")} aria-hidden />
        {trailing.text}
      </p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RotateCcw /> Tentar novamente
        </Button>
      )}
    </div>
  );
}

function Composer({
  disabled,
  busy,
  onSend,
  onStop,
  hint,
  perHour,
}: {
  disabled: boolean;
  busy: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  hint?: string;
  perHour: number | undefined;
}) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [value]);

  const submit = () => {
    if (busy || disabled || !value.trim()) return;
    onSend(value);
    setValue("");
  };
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="border-t border-border bg-card px-3 pt-3 pb-2 md:px-4">
      {hint && <p className="mb-2 text-xs text-warning">{hint}</p>}
      <div className="flex items-end gap-2 rounded-xl border border-border-strong bg-background px-3 py-2 focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/30">
        <textarea
          ref={ref}
          rows={1}
          value={value}
          maxLength={MAX_LENGTH}
          disabled={disabled}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Pergunte sobre sua carteira, um ativo ou os sinais…"
          aria-label="Mensagem para o Voryn AI"
          className="max-h-40 min-h-6 flex-1 resize-none bg-transparent py-1 text-sm text-foreground outline-none placeholder:text-muted-foreground disabled:opacity-60"
        />
        {busy ? (
          <Button size="icon" variant="outline" aria-label="Parar resposta" onClick={onStop}>
            <Square className="size-3.5 fill-current" />
          </Button>
        ) : (
          <Button size="icon" aria-label="Enviar" disabled={disabled || !value.trim()} onClick={submit}>
            <ArrowUp />
          </Button>
        )}
      </div>
      <p className="mt-2 px-1 text-[11px] leading-snug text-muted-foreground">
        O Voryn AI interpreta dados calculados pela plataforma, não acessa notícias, não é recomendação de
        investimento e nunca executa ordens.
        {perHour ? ` Limite de ${perHour} mensagens por hora.` : ""}
        {value.length > MAX_LENGTH - 500 && ` ${value.length}/${MAX_LENGTH}`}
      </p>
    </div>
  );
}
