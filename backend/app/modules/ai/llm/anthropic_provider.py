"""Anthropic (Claude) adapter for the LLM layer.

- Streams with the async SDK and replays assistant content unchanged (thinking blocks
  included), keeping the conversation append-only.
- Adaptive thinking is always on for the configured model; depth is set with `effort`.
- Server-side refusal fallback (`fallbacks: "default"`) is enabled: a request declined by
  a safety classifier is re-run on Anthropic's recommended model instead of failing.
- The frozen system prompt and tool list are prompt-cached (top-level auto caching);
  per-request context travels in the user message, after the cached prefix.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.ai.llm.base import (
    LLMError,
    ProviderEvent,
    StopReason,
    TextDelta,
    ToolCall,
    ToolResult,
    ToolSpec,
    ToolStarted,
    TurnComplete,
    Usage,
)

logger = get_logger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
_STOP_REASONS: dict[str | None, StopReason] = {
    "end_turn": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
}


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, client: anthropic.AsyncAnthropic | None = None) -> None:
        settings = get_settings()
        self.model = settings.ai_model
        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        self._client = client or anthropic.AsyncAnthropic(api_key=key, max_retries=3, timeout=120.0)

    def user_message(self, blocks: list[str]) -> dict[str, Any]:
        return {"role": "user", "content": [{"type": "text", "text": b} for b in blocks]}

    def tool_results_message(self, results: list[ToolResult]) -> dict[str, Any]:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": r.call_id,
                    "content": r.content,
                    **({"is_error": True} if r.is_error else {}),
                }
                for r in results
            ],
        }

    async def stream_turn(
        self, *, system: str, history: list[dict[str, Any]], tools: list[ToolSpec]
    ) -> AsyncIterator[ProviderEvent]:
        settings = get_settings()
        tool_defs: list[Any] = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
                # Inputs stream as generated; the loop validates them before running a tool.
                "eager_input_streaming": True,
            }
            for t in tools
        ]
        try:
            async with self._client.beta.messages.stream(
                model=self.model,
                max_tokens=settings.ai_max_tokens,
                system=system,
                messages=history,  # type: ignore[arg-type]
                tools=tool_defs,
                thinking={"type": "adaptive"},
                output_config={"effort": settings.ai_effort},
                cache_control={"type": "ephemeral"},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                async for event in stream:
                    if event.type == "text":
                        yield TextDelta(event.text)
                    elif (
                        event.type == "content_block_start"
                        and event.content_block.type == "tool_use"
                    ):
                        yield ToolStarted(event.content_block.name)
                message = await stream.get_final_message()
        except anthropic.RateLimitError as exc:
            raise LLMError(
                "A Voryn AI está com alta demanda. Tente novamente em instantes.", retryable=True
            ) from exc
        except anthropic.AuthenticationError as exc:
            logger.error("ai_auth_failed")
            raise LLMError("A Voryn AI não está configurada corretamente.") from exc
        except anthropic.BadRequestError as exc:
            logger.error("ai_bad_request", error=str(exc.message)[:500])
            raise LLMError(
                "Não foi possível processar esta conversa. Inicie uma nova conversa."
            ) from exc
        except anthropic.APIStatusError as exc:
            logger.warning("ai_api_error", status=exc.status_code)
            raise LLMError("A Voryn AI está temporariamente indisponível.", retryable=True) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Não foi possível conectar à Voryn AI.", retryable=True) from exc
        except ValueError as exc:
            # Tool input JSON the SDK could not parse at all (eager input streaming).
            raise LLMError("A resposta foi interrompida. Tente novamente.", retryable=True) from exc

        calls = [
            ToolCall(block.id, block.name, block.input)
            for block in message.content
            if block.type == "tool_use"
        ]
        text = "".join(block.text for block in message.content if block.type == "text")
        usage = message.usage
        yield TurnComplete(
            # Exact replay: every block (thinking, fallback markers, tool_use) is kept.
            assistant_message={
                "role": "assistant",
                "content": [b.model_dump(mode="json", exclude_none=True) for b in message.content],
            },
            text=text,
            tool_calls=calls,
            stop_reason=_STOP_REASONS.get(message.stop_reason, "other"),
            usage=Usage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_input_tokens or 0,
                cache_write_tokens=usage.cache_creation_input_tokens or 0,
            ),
            model=message.model,
            extra={"request_id": getattr(stream, "request_id", None)},
        )


def dumps(value: Any) -> str:
    """Stable, compact JSON for tool results (sorted keys keep cached prefixes stable)."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
