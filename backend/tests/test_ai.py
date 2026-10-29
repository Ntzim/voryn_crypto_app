"""Voryn AI: assistant loop, tools, history integrity, limits and the Anthropic adapter."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.ai import service as ai_service
from app.modules.ai import tools as ai_tools
from app.modules.ai.llm import anthropic_provider
from app.modules.ai.llm.anthropic_provider import AnthropicProvider
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
from app.modules.ai.models import AIMessage
from app.modules.market_data import service as market
from app.modules.portfolio import router as portfolio_router
from app.modules.users.models import User
from tests.conftest import API, ClientFactory, Outbox, login, register_verified
from tests.fakes import FakeCandles, FakeFxHistory, FakeProvider, quote


class ScriptedProvider:
    """Plays back scripted turns; records the history it was given on each call."""

    name = "anthropic"
    model = "scripted-model"

    def __init__(self, turns: list[Any]) -> None:
        self.turns = list(turns)
        self.histories: list[list[dict[str, Any]]] = []
        self.counter = 0

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
                    "is_error": r.is_error,
                }
                for r in results
            ],
        }

    async def stream_turn(
        self, *, system: str, history: list[dict[str, Any]], tools: list[ToolSpec]
    ) -> AsyncIterator[ProviderEvent]:
        self.histories.append(json.loads(json.dumps(history)))
        assert "nunca" in system.lower() or "Nunca" in system
        step = self.turns.pop(0)
        if isinstance(step, Exception):
            raise step
        kind, payload = step
        if kind == "tools":
            calls = []
            for name, args in payload:
                self.counter += 1
                yield ToolStarted(name)
                calls.append(ToolCall(f"call_{self.counter}", name, args))
            content = [
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in calls
            ]
            yield TurnComplete(
                {"role": "assistant", "content": content},
                "",
                calls,
                "tool_use",
                Usage(100, 20, 80),
                self.model,
            )
        else:
            for chunk in payload.split(" "):
                yield TextDelta(chunk + " ")
            stop: StopReason = "refusal" if kind == "refusal" else "end_turn"
            content = [{"type": "text", "text": payload}]
            yield TurnComplete(
                {"role": "assistant", "content": content},
                payload,
                [],
                stop,
                Usage(150, 60, 120),
                self.model,
            )


def parse_sse(body: str) -> list[tuple[str, Any]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events


@pytest.fixture
async def chat_user(
    client: httpx.AsyncClient, outbox: Outbox, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    await market.sync_markets(db, FakeProvider([quote("bitcoin", "BTC", 1, "100000", change="2")]))
    await market.sync_fx(db, FakeProvider([], rate="5"))
    monkeypatch.setattr(ai_service, "BinanceCandleProvider", lambda: FakeCandles({}))
    await register_verified(client, outbox)
    await login(client)
    return client


def use(monkeypatch: pytest.MonkeyPatch, provider: ScriptedProvider) -> None:
    monkeypatch.setattr(ai_service, "provider_or_none", lambda: provider)


async def send(client: httpx.AsyncClient, conv_id: str, text: str) -> list[tuple[str, Any]]:
    response = await client.post(
        f"{API}/ai/conversations/{conv_id}/messages", json={"content": text}
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


async def test_disabled_without_api_key(chat_user: httpx.AsyncClient) -> None:
    status = (await chat_user.get(f"{API}/ai/status")).json()
    assert status["enabled"] is False
    response = await chat_user.post(f"{API}/ai/conversations")
    assert response.status_code == 503 and response.json()["error"]["code"] == "ai_unavailable"


async def test_tool_loop_streams_and_stores_append_only_history(
    chat_user: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, db: AsyncSession
) -> None:
    provider = ScriptedProvider(
        [
            ("tools", [("get_portfolio_summary", {}), ("get_asset_overview", {"asset": "BTC"})]),
            ("text", "Dados observados: sua carteira está vazia e o BTC subiu 2,00% em 24h."),
            ("text", "Segunda resposta."),
        ]
    )
    use(monkeypatch, provider)
    conv = (await chat_user.post(f"{API}/ai/conversations")).json()
    events = await send(chat_user, conv["id"], "Como está minha carteira?")

    kinds = [e for e, _ in events]
    assert kinds[0] == "start" and kinds[-1] == "done"
    assert ("status", {"text": "Consultando sua carteira…"}) in events
    streamed = "".join(d["text"] for e, d in events if e == "delta")
    assert "BTC subiu 2,00%" in streamed
    done = events[-1][1]
    assert any(s.startswith("Mercado BTC · CoinGecko") for s in done["sources"])
    assert {c["name"] for c in done["tool_calls"]} == {
        "get_portfolio_summary",
        "get_asset_overview",
    }

    # The model received tool results built from the deterministic engines.
    tool_turn = provider.histories[1][-1]["content"]
    summary = json.loads(tool_turn[0]["content"])
    assert summary["data"]["empty"] is True
    overview = json.loads(tool_turn[1]["content"])
    assert overview["data"]["price_usd"].startswith("100000")
    # The session context (date, currency) travels in the user message, not the system prompt.
    assert "moeda base do usuário: BRL" in provider.histories[0][-1]["content"][0]["text"]

    await send(chat_user, conv["id"], "E agora?")
    # Append-only: the second turn replays the first turn's history byte for byte.
    assert provider.histories[2][: len(provider.histories[1])] == provider.histories[1]

    detail = (await chat_user.get(f"{API}/ai/conversations/{conv['id']}")).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]
    assert detail["title"] == "Como está minha carteira?" and detail["turns"] == 2
    assert await db.scalar(select(func.count()).select_from(AIMessage)) == 6


async def test_tool_errors_are_reported_to_the_model(
    chat_user: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ScriptedProvider(
        [
            (
                "tools",
                [
                    ("get_asset_overview", {"asset": "NAOEXISTE"}),
                    ("get_asset_overview", {"wrong": 1}),
                ],
            ),
            ("text", "Não encontrei esse ativo."),
        ]
    )
    use(monkeypatch, provider)
    conv = (await chat_user.post(f"{API}/ai/conversations")).json()
    await send(chat_user, conv["id"], "Preço do NAOEXISTE?")
    results = provider.histories[1][-1]["content"]
    assert results[0]["is_error"] and "não encontrado" in results[0]["content"]
    assert results[1]["is_error"] and "Parâmetros inválidos" in results[1]["content"]


async def test_refusal_and_provider_failure_keep_history_valid(
    chat_user: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, db: AsyncSession
) -> None:
    provider = ScriptedProvider(
        [
            ("refusal", "..."),
            ("tools", [("get_market_overview", {})]),
            LLMError("A Voryn AI está temporariamente indisponível.", retryable=True),
            ("text", "Tudo certo agora."),
        ]
    )
    use(monkeypatch, provider)
    conv = (await chat_user.post(f"{API}/ai/conversations")).json()

    events = await send(chat_user, conv["id"], "pedido estranho")
    assert ("notice", {"text": ai_service.REFUSAL_NOTICE}) in events

    # Tool round succeeds, then the provider fails: nothing of that turn is persisted,
    # so no tool_use is left without its tool_result.
    events = await send(chat_user, conv["id"], "e o mercado?")
    assert events[-1][0] == "error" and events[-1][1]["retryable"] is True
    roles = list((await db.execute(select(AIMessage.role).order_by(AIMessage.id))).scalars())
    assert roles == ["user", "assistant", "user"]

    events = await send(chat_user, conv["id"], "tente de novo")
    assert events[-1][0] == "done"
    last_history = provider.histories[-1]
    assert not any(
        block.get("type") == "tool_use"
        for m in last_history
        for block in m["content"]
        if isinstance(block, dict)
    )


async def test_rounds_are_bounded(
    chat_user: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, db: AsyncSession
) -> None:
    rounds = get_settings().ai_max_tool_rounds
    provider = ScriptedProvider([("tools", [("get_market_overview", {})])] * rounds)
    use(monkeypatch, provider)
    conv = (await chat_user.post(f"{API}/ai/conversations")).json()
    events = await send(chat_user, conv["id"], "loop")
    assert any(e == "notice" and "dados demais" in d["text"] for e, d in events)
    roles = list((await db.execute(select(AIMessage.role))).scalars())
    assert roles == ["user"]  # the unanswered tool exchange was not stored


async def test_limits_and_isolation(
    chat_user: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    client_factory: ClientFactory,
    outbox: Outbox,
) -> None:
    provider = ScriptedProvider([("text", "ok")] * 5)
    use(monkeypatch, provider)
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_max_turns_per_conversation", 2)
    conv = (await chat_user.post(f"{API}/ai/conversations")).json()
    await send(chat_user, conv["id"], "1")
    await send(chat_user, conv["id"], "2")
    response = await chat_user.post(
        f"{API}/ai/conversations/{conv['id']}/messages", json={"content": "3"}
    )
    assert response.status_code == 409

    monkeypatch.setattr(settings, "ai_messages_per_hour", 2)
    conv2 = (await chat_user.post(f"{API}/ai/conversations")).json()
    response = await chat_user.post(
        f"{API}/ai/conversations/{conv2['id']}/messages", json={"content": "x"}
    )
    assert response.status_code == 429

    eve = await client_factory()
    await register_verified(eve, outbox, email="eve@example.com", name="Eve")
    await login(eve, email="eve@example.com")
    assert (await eve.get(f"{API}/ai/conversations/{conv['id']}")).status_code == 404
    response = await eve.post(
        f"{API}/ai/conversations/{conv['id']}/messages", json={"content": "oi"}
    )
    assert response.status_code == 404
    assert (await eve.get(f"{API}/ai/conversations")).json() == []


async def test_realized_operations_rank_trades(
    chat_user: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, db: AsyncSession
) -> None:
    today = datetime.now(UTC).date()
    ptax = FakeFxHistory({today - timedelta(days=n): Decimal("5") for n in range(1, 10)})
    monkeypatch.setattr(portfolio_router, "BcbPtaxProvider", lambda: ptax)
    pid = (await chat_user.get(f"{API}/portfolios")).json()[0]["id"]
    btc = (await chat_user.get(f"{API}/market/search", params={"q": "btc"})).json()[0]["id"]

    def at(days: int) -> str:
        return datetime.combine(today - timedelta(days=days), time(15), UTC).isoformat()

    for body in (
        {"type": "buy", "quantity": "2", "unit_price": "100", "executed_at": at(5)},
        {"type": "sell", "quantity": "1", "unit_price": "150", "executed_at": at(4)},  # +50
        {"type": "sell", "quantity": "0.5", "unit_price": "80", "executed_at": at(3)},  # −10
    ):
        response = await chat_user.post(
            f"{API}/portfolios/{pid}/transactions",
            json={"asset_id": btc, "quote_currency": "BRL", **body},
        )
        assert response.status_code == 201, response.text

    user_id = (await db.execute(select(User.id))).scalar_one()
    ctx = ai_tools.ToolContext(db, user_id, "BRL", FakeCandles({}))
    output, error = await ai_tools.run_tool(ctx, "get_realized_operations", {})
    assert error is None and output is not None
    assert [op["realized_pnl"] for op in output.data["operations"]] == ["50.00", "-10.00"]


# --------------------------------------------------------------------------- Anthropic adapter


class _FakeStream:
    def __init__(self, events: list[Any], message: Any) -> None:
        self.events, self.message = events, message

    async def __aenter__(self) -> "_FakeStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __aiter__(self) -> "_FakeStream":
        self._it = iter(self.events)
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration from None

    async def get_final_message(self) -> Any:
        return self.message


async def test_anthropic_adapter_request_shape_and_exact_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from anthropic.types.beta import BetaMessage

    message = BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": [
                {"type": "thinking", "thinking": "", "signature": "sig-abc"},
                {"type": "text", "text": "Vou consultar."},
                {"type": "tool_use", "id": "toolu_1", "name": "get_market_overview", "input": {}},
            ],
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {
                "input_tokens": 1200,
                "output_tokens": 40,
                "cache_read_input_tokens": 1000,
                "cache_creation_input_tokens": 0,
            },
        }
    )
    events = [
        SimpleNamespace(type="text", text="Vou consultar."),
        SimpleNamespace(
            type="content_block_start",
            content_block=SimpleNamespace(type="tool_use", name="get_market_overview"),
        ),
    ]
    captured: dict[str, Any] = {}

    def fake_stream(**kwargs: Any) -> _FakeStream:
        captured.update(kwargs)
        return _FakeStream(events, message)

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=fake_stream)))
    provider = AnthropicProvider(client=client)  # type: ignore[arg-type]
    spec = ToolSpec("get_market_overview", "panorama", {"type": "object", "properties": {}})
    out = [
        e
        async for e in provider.stream_turn(
            system="S", history=[{"role": "user", "content": "oi"}], tools=[spec]
        )
    ]

    assert captured["model"] == "claude-opus-5-5"
    assert (
        captured["fallbacks"] == "default" and anthropic_provider.FALLBACK_BETA in captured["betas"]
    )
    assert captured["thinking"] == {"type": "adaptive"}
    assert captured["output_config"] == {"effort": "medium"}
    assert captured["cache_control"] == {"type": "ephemeral"}
    assert captured["tools"][0]["eager_input_streaming"] is True
    assert "tool_choice" not in captured  # forced tool use is rejected by this model

    assert isinstance(out[0], TextDelta) and isinstance(out[1], ToolStarted)
    turn = out[-1]
    assert isinstance(turn, TurnComplete)
    assert turn.stop_reason == "tool_use" and turn.tool_calls[0].name == "get_market_overview"
    assert turn.usage.cache_read_tokens == 1000
    # Thinking block (with its signature) is kept for exact replay.
    assert turn.assistant_message["content"][0] == {
        "type": "thinking",
        "thinking": "",
        "signature": "sig-abc",
    }
