"""Provider-agnostic contract for the language model layer.

The assistant loop, tools, prompts and persistence depend only on these types. A provider
adapts them to its API and owns its native message format: history is stored in that
native form (so it can be replayed byte-for-byte, as some providers require), and the
provider builds every native message the loop needs.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


class LLMError(Exception):
    """The provider failed; `user_message` is safe to show."""

    def __init__(self, user_message: str, *, retryable: bool = False) -> None:
        self.user_message = user_message
        self.retryable = retryable
        super().__init__(user_message)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    input: Any


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


StopReason = Literal["end_turn", "tool_use", "max_tokens", "refusal", "other"]


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ToolStarted:
    name: str


@dataclass(frozen=True, slots=True)
class TurnComplete:
    #: provider-native assistant message, appended to history unchanged
    assistant_message: dict[str, Any]
    text: str
    tool_calls: list[ToolCall]
    stop_reason: StopReason
    usage: Usage
    model: str
    extra: dict[str, Any] = field(default_factory=dict)


ProviderEvent = TextDelta | ToolStarted | TurnComplete


class LLMProvider(Protocol):
    name: str
    model: str

    def user_message(self, blocks: list[str]) -> dict[str, Any]: ...

    def tool_results_message(self, results: list[ToolResult]) -> dict[str, Any]: ...

    def stream_turn(
        self, *, system: str, history: list[dict[str, Any]], tools: list[ToolSpec]
    ) -> AsyncIterator[ProviderEvent]: ...
