"""Voryn AI: conversations and the provider-agnostic assistant loop.

Flow per user message (spec §10): the model receives the question and the tool catalogue,
calls read-only tools backed by the deterministic engines, and explains the results.
Events are streamed to the browser as they happen.

Integrity rules:
- History is append-only and replayed exactly (never edited or trimmed).
- A turn's assistant/tool messages are committed together at the end, so a failure
  mid-turn can never leave a tool call without its result in the stored history.
"""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import rate_limit
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.modules.ai import tools as ai_tools
from app.modules.ai.llm.anthropic_provider import AnthropicProvider, dumps
from app.modules.ai.llm.base import (
    LLMError,
    LLMProvider,
    TextDelta,
    ToolResult,
    ToolStarted,
    TurnComplete,
)
from app.modules.ai.models import AIConversation, AIMessage
from app.modules.ai.prompts import PROMPT_VERSION, SYSTEM_PROMPT, session_context
from app.modules.market_data.providers.base import CandleProvider
from app.modules.market_data.providers.binance import BinanceCandleProvider
from app.modules.users.models import User

logger = get_logger(__name__)

REFUSAL_NOTICE = (
    "Não posso ajudar com esse pedido. Posso explicar sua carteira, os indicadores e os sinais "
    "da plataforma."
)


class AIUnavailableError(AppError):
    status_code = 503
    code = "ai_unavailable"
    message = "A Voryn AI não está configurada neste ambiente."


def provider_or_none() -> LLMProvider | None:
    settings = get_settings()
    if settings.ai_provider == "disabled" or settings.anthropic_api_key is None:
        return None
    return AnthropicProvider()


# --------------------------------------------------------------------------- conversations


async def list_conversations(db: AsyncSession, user_id: uuid.UUID) -> list[AIConversation]:
    return list(
        (
            await db.execute(
                select(AIConversation)
                .where(AIConversation.user_id == user_id)
                .order_by(AIConversation.updated_at.desc())
                .limit(50)
            )
        ).scalars()
    )


async def get_owned(
    db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> AIConversation:
    conv = (
        await db.execute(
            select(AIConversation).where(
                AIConversation.id == conversation_id, AIConversation.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise NotFoundError("Conversa não encontrada.")
    return conv


async def create_conversation(
    db: AsyncSession, user_id: uuid.UUID, provider: LLMProvider
) -> AIConversation:
    conv = AIConversation(
        user_id=user_id,
        title="Nova conversa",
        provider=provider.name,
        model=provider.model,
        prompt_version=PROMPT_VERSION,
        turns=0,
    )
    db.add(conv)
    await db.commit()
    return conv


async def delete_conversation(db: AsyncSession, conv: AIConversation) -> None:
    await db.delete(conv)
    await db.commit()


async def visible_messages(db: AsyncSession, conv: AIConversation) -> list[AIMessage]:
    return list(
        (
            await db.execute(
                select(AIMessage)
                .where(AIMessage.conversation_id == conv.id, AIMessage.display_text.is_not(None))
                .order_by(AIMessage.id)
            )
        ).scalars()
    )


async def usage_today(db: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(AIMessage.input_tokens), 0),
                func.coalesce(func.sum(AIMessage.output_tokens), 0),
                func.coalesce(func.sum(AIMessage.cache_read_tokens), 0),
            )
            .join(AIConversation, AIConversation.id == AIMessage.conversation_id)
            .where(AIConversation.user_id == user_id, AIMessage.created_at >= start)
        )
    ).one()
    return {
        "input_tokens": int(row[0]),
        "output_tokens": int(row[1]),
        "cache_read_tokens": int(row[2]),
    }


# --------------------------------------------------------------------------- chat


async def check_can_send(
    db: AsyncSession, user: User, conv: AIConversation, provider: LLMProvider
) -> None:
    """Pre-flight checks, raised as normal JSON errors before the stream starts."""
    settings = get_settings()
    if conv.provider != provider.name:
        raise ConflictError(
            "Esta conversa foi criada com outro provedor de IA. Inicie uma nova conversa."
        )
    if conv.turns >= settings.ai_max_turns_per_conversation:
        raise ConflictError(
            "Esta conversa atingiu o limite de mensagens. Inicie uma nova conversa para continuar."
        )
    await rate_limit.enforce(f"ai:hour:{user.id}", settings.ai_messages_per_hour, 3600)
    await rate_limit.enforce(f"ai:day:{user.id}", settings.ai_messages_per_day, 86400)


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def stream_reply(
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    text: str,
    provider: LLMProvider,
) -> AsyncIterator[str]:
    """Run one assistant turn, yielding Server-Sent Events.

    Owns its DB session and candle client: a streaming response outlives the request's
    dependencies.
    """
    candles = BinanceCandleProvider()
    try:
        async for chunk in _reply(user_id, conversation_id, text, provider, candles):
            yield chunk
    finally:
        await candles.aclose()


async def _reply(
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    text: str,
    provider: LLMProvider,
    candles: CandleProvider,
) -> AsyncIterator[str]:
    settings = get_settings()
    async with get_sessionmaker()() as db:
        conv = await get_owned(db, user_id, conversation_id)
        user = (
            await db.execute(
                select(User).where(User.id == user_id).options(selectinload(User.settings))
            )
        ).scalar_one()
        history = [
            m.native
            for m in (
                await db.execute(
                    select(AIMessage)
                    .where(AIMessage.conversation_id == conv.id)
                    .order_by(AIMessage.id)
                )
            ).scalars()
        ]

        tz = ZoneInfo(user.settings.timezone)
        context = session_context(
            now_local=datetime.now(tz).strftime("%d/%m/%Y %H:%M"),
            timezone=user.settings.timezone,
            currency=user.settings.base_currency,
        )
        user_native = provider.user_message([context, text])
        db.add(
            AIMessage(conversation_id=conv.id, role="user", native=user_native, display_text=text)
        )
        if conv.turns == 0:
            conv.title = (text[:117] + "…") if len(text) > 120 else text
        await db.commit()
        history.append(user_native)
        yield _sse("start", {"conversation_id": str(conv.id)})

        ctx = ai_tools.ToolContext(db, user.id, user.settings.base_currency, candles)  # type: ignore[arg-type]
        specs = [t.spec for t in ai_tools.TOOLS]
        pending: list[AIMessage] = []
        answer: list[str] = []
        calls_log: list[dict[str, Any]] = []
        sources: list[str] = []
        notice: str | None = None
        last: TurnComplete | None = None
        try:
            for _ in range(settings.ai_max_tool_rounds):
                turn: TurnComplete | None = None
                async for event in provider.stream_turn(
                    system=SYSTEM_PROMPT, history=history, tools=specs
                ):
                    if isinstance(event, TextDelta):
                        yield _sse("delta", {"text": event.text})
                    elif isinstance(event, ToolStarted):
                        tool = ai_tools.TOOLS_BY_NAME.get(event.name)
                        yield _sse(
                            "status", {"text": (tool.status if tool else "Consultando dados") + "…"}
                        )
                    elif isinstance(event, TurnComplete):
                        turn = event
                if turn is None:
                    raise LLMError("A resposta foi interrompida. Tente novamente.", retryable=True)
                last = turn
                history.append(turn.assistant_message)
                if turn.text:
                    answer.append(turn.text)
                message = AIMessage(
                    conversation_id=conv.id,
                    role="assistant",
                    native=turn.assistant_message,
                    stop_reason=turn.stop_reason,
                    model=turn.model,
                    input_tokens=turn.usage.input_tokens,
                    output_tokens=turn.usage.output_tokens,
                    cache_read_tokens=turn.usage.cache_read_tokens,
                )
                pending.append(message)

                if turn.stop_reason == "refusal":
                    notice = REFUSAL_NOTICE
                    break
                if not turn.tool_calls:
                    break
                if turn.stop_reason == "max_tokens":
                    # A truncated tool input must not run; the turn is unusable.
                    raise LLMError(
                        "A resposta ficou longa demais. Reformule a pergunta de forma mais "
                        "específica."
                    )

                results: list[ToolResult] = []
                for call in turn.tool_calls:
                    output, error = await ai_tools.run_tool(ctx, call.name, call.input)
                    calls_log.append({"name": call.name, "input": call.input, "ok": error is None})
                    if output is not None:
                        sources.append(output.source)
                        content = dumps({"source": output.source, "data": output.data})
                    else:
                        content = dumps({"error": error})
                    results.append(ToolResult(call.id, content, is_error=error is not None))
                tool_native = provider.tool_results_message(results)
                history.append(tool_native)
                pending.append(
                    AIMessage(conversation_id=conv.id, role="tool_results", native=tool_native)
                )
            else:
                # Out of rounds while the model still wanted data: close the turn honestly.
                notice = (
                    "A consulta exigiu dados demais para uma única resposta. "
                    "Faça uma pergunta mais específica."
                )
                raise _RoundsExhaustedError()
        except _RoundsExhaustedError:
            # The last stored message is a tool result the model never answered; drop the
            # whole turn rather than persist an unanswered tool exchange.
            pending.clear()
            yield _sse("notice", {"text": notice})
            yield _sse("done", {"sources": sources, "tool_calls": calls_log})
            return
        except LLMError as exc:
            await db.rollback()
            yield _sse("error", {"text": exc.user_message, "retryable": exc.retryable})
            return

        final_text = "\n\n".join(answer).strip() or (notice or "")
        if pending:
            final = pending[-1] if pending[-1].role == "assistant" else None
            if final is not None:
                final.display_text = final_text
                final.tool_calls = calls_log
                final.sources = list(dict.fromkeys(sources))
        db.add_all(pending)
        conv.turns += 1
        conv.updated_at = datetime.now(UTC)
        await db.commit()
        if notice:
            yield _sse("notice", {"text": notice})
        yield _sse(
            "done",
            {
                "sources": list(dict.fromkeys(sources)),
                "tool_calls": calls_log,
                "model": last.model if last else None,
                "stop_reason": last.stop_reason if last else None,
            },
        )


class _RoundsExhaustedError(Exception):
    pass
