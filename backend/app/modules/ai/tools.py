"""Read-only tools the assistant can call.

Every tool returns figures computed by the deterministic engines (portfolio, technical
analysis, signals, market data) plus `as_of` provenance. The model interprets; it never
computes or invents numbers. No tool can place orders or modify anything.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.ai.llm.base import ToolSpec
from app.modules.market_data import service as market
from app.modules.market_data.providers.base import CandleProvider, ProviderError
from app.modules.portfolio import service as portfolio
from app.modules.portfolio.engine import Ledger
from app.modules.risk import service as risk
from app.modules.risk.schemas import ScenarioIn, ScenarioOverride
from app.modules.signals import service as signals
from app.modules.technical_analysis import service as analysis

Currency = Literal["BRL", "USD"]
Timeframe = Literal["15m", "1h", "4h", "1d", "1w"]


@dataclass(frozen=True, slots=True)
class ToolContext:
    db: AsyncSession
    user_id: uuid.UUID
    currency: Currency
    candles: CandleProvider


@dataclass(frozen=True, slots=True)
class ToolOutput:
    data: dict[str, Any]
    #: human-readable provenance, e.g. "Carteira · preços de 28/10 21:30 UTC"
    source: str


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(_Args):
    pass


class CurrencyArgs(_Args):
    currency: Currency | None = Field(
        default=None, description="BRL ou USD; padrão: moeda do usuário"
    )


class TransactionsArgs(_Args):
    asset: str | None = Field(
        default=None, description="Símbolo ou identificador do ativo, ex.: BTC"
    )
    limit: int = Field(default=20, ge=1, le=100)


class AssetArgs(_Args):
    asset: str = Field(description="Símbolo (BTC) ou identificador (bitcoin) do ativo")


class AnalysisArgs(AssetArgs):
    timeframe: Timeframe = "1d"


class SignalListArgs(_Args):
    timeframe: Literal["1d", "4h"] = "1d"
    classification: Literal["buy_potential", "neutral", "attention", "sell_potential"] | None = None
    limit: int = Field(default=10, ge=1, le=30)


class RiskArgs(CurrencyArgs):
    window: int = Field(default=365, ge=30, le=365, description="Dias de histórico")


class ScenarioShock(_Args):
    asset: str = Field(description="Símbolo ou identificador do ativo")
    change_pct: Decimal = Field(ge=-100, le=1000)


class ScenarioArgs(CurrencyArgs):
    btc_change_pct: Decimal = Field(ge=-100, le=1000, description="Variação do Bitcoin, em %")
    overrides: list[ScenarioShock] = Field(
        default_factory=list, max_length=20, description="Variações específicas por ativo"
    )


class SearchArgs(_Args):
    query: str = Field(min_length=1, max_length=64)


def _q(v: Decimal | None, places: str = "0.01") -> str | None:
    return None if v is None else str(v.quantize(Decimal(places)))


def _stamp(dt: datetime | None) -> str:
    return dt.astimezone(UTC).strftime("%d/%m/%Y %H:%M UTC") if dt else "indisponível"


async def _resolve(ctx: ToolContext, ref: str) -> Any:
    crypto = await market.resolve_asset(ctx.db, ref)
    if crypto is None:
        raise ToolUserError(f"Ativo “{ref}” não encontrado no catálogo da Voryn.")
    return crypto


class ToolUserError(Exception):
    """A tool failure the model should see and explain (bad asset, no data...)."""


# --------------------------------------------------------------------------- handlers


async def portfolio_summary(ctx: ToolContext, args: CurrencyArgs) -> ToolOutput:
    currency = args.currency or ctx.currency
    pf = (await portfolio.list_portfolios(ctx.db, ctx.user_id))[0]
    s = await portfolio.summary(ctx.db, pf, currency)
    if s.transaction_count == 0:
        return ToolOutput(
            {"empty": True, "message": "O usuário ainda não registrou transações."},
            "Carteira (vazia)",
        )
    data = {
        "currency": currency,
        "as_of": s.as_of.isoformat(),
        "market_value": _q(s.market_value),
        "market_value_usd": _q(s.market_value_usd),
        "market_value_brl": _q(s.market_value_brl),
        "cost_basis": _q(s.cost_basis),
        "unrealized_pnl": _q(s.unrealized_pnl),
        "realized_pnl": _q(s.realized_pnl),
        "total_pnl": _q(s.total_pnl),
        "net_invested": _q(s.net_invested),
        "fees": _q(s.fees),
        "change_24h": {
            "market_effect": _q(s.change_24h.market_effect),
            "net_flows": _q(s.change_24h.net_flows),
            "pct": _q(s.change_24h.pct),
        },
        "prices_stale": s.prices.is_stale,
        "assets_without_live_price": s.prices.missing_assets,
        "positions": [
            {
                "symbol": p.asset.symbol,
                "name": p.asset.name,
                "quantity": str(p.quantity.normalize()),
                "price": _q(p.price, "0.00000001"),
                "market_value": _q(p.market_value),
                "average_cost": _q(p.average_cost, "0.00000001"),
                "unrealized_pnl": _q(p.unrealized_pnl),
                "unrealized_pct": _q(p.unrealized_pct),
                "realized_pnl": _q(p.realized_pnl),
                "weight_pct": _q(p.weight_pct),
                "change_pct_24h": _q(p.change_pct_24h),
            }
            for p in s.positions
        ],
        "closed_positions": [
            {"symbol": p.asset.symbol, "realized_pnl": _q(p.realized_pnl)}
            for p in s.closed_positions
        ],
        "transaction_count": s.transaction_count,
    }
    return ToolOutput(data, f"Carteira · preços de {_stamp(s.prices.fetched_at)}")


async def portfolio_performance(ctx: ToolContext, args: CurrencyArgs) -> ToolOutput:
    currency = args.currency or ctx.currency
    pf = (await portfolio.list_portfolios(ctx.db, ctx.user_id))[0]
    perf = await portfolio.performance(ctx.db, pf, currency)
    # Weekly samples keep the payload small while preserving the shape of the curve.
    sampled = perf.series[::7] + (perf.series[-1:] if perf.series else [])
    data = {
        "currency": currency,
        "inception_date": perf.inception_date.isoformat() if perf.inception_date else None,
        "history_start": perf.history_start.isoformat() if perf.history_start else None,
        "history_complete": perf.history_complete,
        "twr_returns_pct": perf.returns.model_dump(mode="json"),
        "xirr_annual_pct": str(perf.xirr_pct) if perf.xirr_pct is not None else None,
        "xirr_applicable": perf.xirr_applicable,
        "weekly_series": [
            {
                "day": p.day.isoformat(),
                "value": _q(p.value),
                "net_invested": _q(p.net_invested),
                "twr_pct": _q(p.twr_pct),
                "btc_pct": _q(p.btc_pct),
                "eth_pct": _q(p.eth_pct),
            }
            for p in sampled
        ],
        "methodology": (
            "TWR diário encadeado sobre fechamentos UTC; XIRR anualizado sobre aportes e retiradas."
        ),
    }
    return ToolOutput(data, f"Rentabilidade da carteira · até {_stamp(perf.as_of)}")


async def portfolio_insights(ctx: ToolContext, args: NoArgs) -> ToolOutput:
    pf = (await portfolio.list_portfolios(ctx.db, ctx.user_id))[0]
    out = await portfolio.insights(ctx.db, pf, ctx.currency)
    return ToolOutput(
        {"insights": [i.model_dump(mode="json") for i in out.items]},
        f"Insights da carteira · {_stamp(out.as_of)}",
    )


async def realized_operations(ctx: ToolContext, args: TransactionsArgs) -> ToolOutput:
    """Realized result of each disposal (sell / conversion / fee), from the position engine."""
    pf = (await portfolio.list_portfolios(ctx.db, ctx.user_id))[0]
    txs = await portfolio.transactions(ctx.db, pf.id)
    entries = portfolio.ledger_entries(txs, ctx.currency)
    tx_by_id = {str(t.id): t for t in txs}
    cryptos = await market.cryptos_by_id(ctx.db, list({t.cryptocurrency_id for t in txs}))
    asset_filter = (await _resolve(ctx, args.asset)).id if args.asset else None

    ledger = Ledger()
    operations = []
    for entry in entries:
        before = ledger.position(entry.asset).realized_pnl
        ledger.apply(entry)
        realized = ledger.position(entry.asset).realized_pnl - before
        if realized == 0 or (asset_filter and entry.asset != asset_filter):
            continue
        tx = tx_by_id[entry.id]
        operations.append(
            {
                "date": tx.executed_at.isoformat(),
                "type": tx.type.value,
                "symbol": cryptos[entry.asset].symbol,
                "quantity": str(tx.quantity.normalize()),
                "realized_pnl": _q(realized),
                "proceeds": _q(entry.gross - entry.fee) if entry.gross is not None else None,
            }
        )
    operations.sort(key=lambda o: Decimal(o["realized_pnl"] or "0"), reverse=True)
    return ToolOutput(
        {
            "currency": ctx.currency,
            "operations": operations[: args.limit],
            "count": len(operations),
        },
        "Resultados realizados (motor de custo médio)",
    )


async def list_transactions(ctx: ToolContext, args: TransactionsArgs) -> ToolOutput:
    pf = (await portfolio.list_portfolios(ctx.db, ctx.user_id))[0]
    asset_id = (await _resolve(ctx, args.asset)).id if args.asset else None
    items, total = await portfolio.list_transactions(
        ctx.db, pf, type_=None, asset_id=asset_id, page=1, page_size=args.limit
    )
    return ToolOutput(
        {
            "total": total,
            "transactions": [
                {
                    "date": t.executed_at.isoformat(),
                    "type": t.type.value,
                    "symbol": t.asset.symbol,
                    "quantity": str(t.quantity.normalize()),
                    "unit_price": str(t.unit_price) if t.unit_price is not None else None,
                    "quote_currency": t.quote_currency,
                    "fee": str(t.fee_amount),
                    "to_symbol": t.to_asset.symbol if t.to_asset else None,
                    "exchange": t.exchange_id,
                }
                for t in items
            ],
        },
        "Transações registradas",
    )


async def asset_overview(ctx: ToolContext, args: AssetArgs) -> ToolOutput:
    crypto = await _resolve(ctx, args.asset)
    detail = await market.get_asset(ctx.db, crypto.source_id, "USD")
    a = detail.asset
    data = {
        "symbol": a.symbol,
        "name": a.name,
        "rank": a.market_cap_rank,
        "price_usd": str(a.price),
        "change_pct": {
            "1h": _q(a.change_pct_1h),
            "24h": _q(a.change_pct_24h),
            "7d": _q(a.change_pct_7d),
        },
        "market_cap_usd": _q(a.market_cap, "1"),
        "volume_24h_usd": _q(a.total_volume, "1"),
        "high_24h": str(a.high_24h) if a.high_24h else None,
        "low_24h": str(a.low_24h) if a.low_24h else None,
        "ath_usd": str(a.ath) if a.ath else None,
        "ath_change_pct": _q(a.ath_change_pct),
        "ath_date": a.ath_date.isoformat() if a.ath_date else None,
        "circulating_supply": _q(a.circulating_supply, "1"),
        "max_supply": _q(a.max_supply, "1"),
        "data_stale": detail.status.is_stale,
    }
    return ToolOutput(data, f"Mercado {a.symbol} · CoinGecko · {_stamp(detail.status.fetched_at)}")


async def technical_analysis(ctx: ToolContext, args: AnalysisArgs) -> ToolOutput:
    crypto = await _resolve(ctx, args.asset)
    result = await analysis.asset_analysis(ctx.db, crypto.source_id, args.timeframe, ctx.candles)
    data = {
        "symbol": result.symbol,
        "timeframe": result.timeframe,
        "pair": result.pair,
        "candles": len(result.candles),
        "data_stale": result.is_stale,
        "last_closed_candle": result.snapshot.model_dump(mode="json") if result.snapshot else None,
        "trend": result.trend.model_dump(mode="json"),
        "supports": [lv.model_dump(mode="json") for lv in result.supports],
        "resistances": [lv.model_dump(mode="json") for lv in result.resistances],
        "methodology_version": result.methodology_version,
        "note": "Indicadores calculados apenas com candles fechados; preços em USDT.",
    }
    candle = _stamp(result.snapshot.as_of) if result.snapshot else "sem candles fechados"
    return ToolOutput(
        data, f"Análise técnica {result.symbol} {result.timeframe} · candle de {candle}"
    )


async def asset_signal(ctx: ToolContext, args: AnalysisArgs) -> ToolOutput:
    crypto = await _resolve(ctx, args.asset)
    s = await signals.for_asset(ctx.db, crypto.source_id, args.timeframe, ctx.candles)
    data = {
        "symbol": s.asset.symbol,
        "timeframe": s.timeframe,
        "score": str(s.score),
        "classification": s.classification,
        "trend": s.trend,
        "components": [c.model_dump(mode="json") for c in s.components],
        "justification": s.justification,
        "risks": s.risks,
        "invalidation": s.invalidation,
        "reference_price": str(s.reference_price),
        "candle_time": s.candle_time.isoformat(),
        "data_stale": s.data_is_stale,
        "data_quality": s.data_quality,
        "quality_reasons": s.quality_reasons,
        "is_current": s.is_current,
        "strategy": f"{s.strategy_key} v{s.strategy_version}",
        "disclaimer": (
            "O score mede o alinhamento de condições favoráveis; não é probabilidade de lucro."
        ),
    }
    if not s.is_current:
        data["historical_notice"] = (
            "Análise histórica: os dados atuais estão indisponíveis ou desatualizados. "
            "Não apresente esta classificação como recomendação atual."
        )
    return ToolOutput(
        data, f"Sinal {s.asset.symbol} {s.timeframe} · candle de {_stamp(s.candle_time)}"
    )


async def list_signals(ctx: ToolContext, args: SignalListArgs) -> ToolOutput:
    items = await signals.list_latest(
        ctx.db, args.timeframe, classification=args.classification, only_ids=None, limit=args.limit
    )
    data = {
        "timeframe": args.timeframe,
        "signals": [
            {
                "symbol": s.asset.symbol,
                "score": str(s.score),
                "classification": s.classification,
                "trend": s.trend,
                "risks": s.risks,
                "candle_time": s.candle_time.isoformat(),
                "data_quality": s.data_quality,
            }
            for s in items
        ],
        "disclaimer": signals.DISCLAIMER,
    }
    return ToolOutput(data, f"Sinais de oportunidade {args.timeframe}")


async def market_overview(ctx: ToolContext, args: NoArgs) -> ToolOutput:
    o = await market.overview(ctx.db, "USD")

    def brief(a: Any) -> dict[str, Any]:
        return {"symbol": a.symbol, "change_24h_pct": _q(a.change_pct_24h)}

    data = {
        "universe": f"{o.tracked_assets} maiores ativos por capitalização (não o mercado inteiro)",
        "total_market_cap_usd": _q(o.total_market_cap, "1"),
        "total_volume_24h_usd": _q(o.total_volume_24h, "1"),
        "btc_dominance_pct": _q(o.btc_dominance_pct),
        "advancers_24h": o.advancers_24h,
        "decliners_24h": o.decliners_24h,
        "top_gainers": [brief(a) for a in o.top_gainers],
        "top_losers": [brief(a) for a in o.top_losers],
        "data_stale": o.status.is_stale,
    }
    return ToolOutput(data, f"Visão de mercado · {_stamp(o.status.fetched_at)}")


async def search_asset(ctx: ToolContext, args: SearchArgs) -> ToolOutput:
    found = await market.search_assets(ctx.db, args.query, limit=8)
    return ToolOutput(
        {
            "results": [
                {"symbol": c.symbol, "id": c.source_id, "name": c.name, "rank": c.market_cap_rank}
                for c in found
            ]
        },
        "Catálogo de ativos",
    )


# --------------------------------------------------------------------------- registry


async def portfolio_risk(ctx: ToolContext, args: RiskArgs) -> ToolOutput:
    pf = (await portfolio.list_portfolios(ctx.db, ctx.user_id))[0]
    out = await risk.portfolio_risk(
        ctx.db, pf, args.currency or ctx.currency, args.window, ctx.candles
    )
    data = out.model_dump(mode="json", exclude={"methodology"})
    return ToolOutput(
        data,
        f"Risco da carteira · {args.window} dias até {out.period_end or 'sem dados'} · "
        f"{_stamp(out.as_of)}",
    )


async def simulate_scenario(ctx: ToolContext, args: ScenarioArgs) -> ToolOutput:
    pf = (await portfolio.list_portfolios(ctx.db, ctx.user_id))[0]
    overrides = [
        ScenarioOverride(asset_id=(await _resolve(ctx, o.asset)).id, change_pct=o.change_pct)
        for o in args.overrides
    ]
    body = ScenarioIn(btc_change_pct=args.btc_change_pct, overrides=overrides)
    out = await risk.scenario(ctx.db, pf, args.currency or ctx.currency, body, ctx.candles)
    return ToolOutput(out.model_dump(mode="json"), f"Simulação de cenário · {_stamp(out.as_of)}")


@dataclass(frozen=True, slots=True)
class Tool:
    spec: ToolSpec
    args: type[_Args]
    handler: Callable[[ToolContext, Any], Awaitable[ToolOutput]]
    status: str  # shown to the user while the tool runs


def _tool(name: str, args: type[_Args], handler: Any, status: str) -> Tool:
    schema = args.model_json_schema()
    schema.pop("title", None)
    return Tool(ToolSpec(name, _DESCRIPTIONS[name], schema), args, handler, status)


_DESCRIPTIONS = {
    "get_portfolio_summary": (
        "Posições atuais do usuário: valor de mercado, custo, resultado realizado e não "
        "realizado, pesos e variação 24h separando efeito de mercado de aportes."
    ),
    "get_portfolio_performance": (
        "Rentabilidade da carteira: TWR por período (24h, 7d, 30d, 90d, 1a, início), XIRR "
        "anualizado e série semanal comparada a BTC e ETH."
    ),
    "get_portfolio_insights": (
        "Pontos de atenção determinísticos da carteira: concentração, stablecoins, movimentos "
        "de 24h, posições abaixo do preço médio e correlação."
    ),
    "get_realized_operations": (
        "Resultado realizado de cada venda, conversão ou taxa, do maior lucro ao maior "
        "prejuízo. Use para perguntas como “qual foi minha melhor operação”."
    ),
    "list_transactions": (
        "Transações registradas pelo usuário, mais recentes primeiro, opcionalmente "
        "filtradas por ativo."
    ),
    "get_asset_overview": (
        "Dados de mercado de um ativo: preço, variações 1h/24h/7d, capitalização, volume, "
        "oferta e máxima histórica."
    ),
    "get_technical_analysis": (
        "Indicadores do último candle fechado (RSI, MACD, EMAs, Bollinger, ATR, volume, "
        "volatilidade), tendência com critérios e suportes/resistências."
    ),
    "get_asset_signal": (
        "Sinal de oportunidade quantitativo de um ativo: score 0–100, classificação, "
        "componentes, riscos e condições de invalidação."
    ),
    "list_signals": (
        "Sinais de oportunidade mais recentes dos ativos acompanhados, ordenados por score, "
        "opcionalmente filtrados por classificação."
    ),
    "get_market_overview": (
        "Panorama do mercado: capitalização e volume agregados, dominância do Bitcoin, "
        "altas e baixas e maiores variações em 24h."
    ),
    "get_portfolio_risk": (
        "Risco da carteira atual sobre o histórico diário: volatilidade, drawdown, VaR "
        "histórico 95/99% e expected shortfall, beta ao BTC, piores janelas de 1/7/30 dias, "
        "concentração, correlação, liquidez e contribuição de cada ativo ao risco."
    ),
    "simulate_scenario": (
        "Simulação mecânica: aplica uma variação do Bitcoin às posições atuais pelo beta de "
        "cada ativo (stablecoins estáveis), com ajustes opcionais por ativo. Não é previsão."
    ),
    "search_asset": (
        "Busca ativos no catálogo por nome ou símbolo, para resolver a qual ativo o usuário "
        "se refere."
    ),
}

TOOLS: list[Tool] = [
    _tool("get_portfolio_summary", CurrencyArgs, portfolio_summary, "Consultando sua carteira"),
    _tool(
        "get_portfolio_performance",
        CurrencyArgs,
        portfolio_performance,
        "Calculando a rentabilidade",
    ),
    _tool("get_portfolio_insights", NoArgs, portfolio_insights, "Verificando pontos de atenção"),
    _tool(
        "get_realized_operations",
        TransactionsArgs,
        realized_operations,
        "Analisando suas operações",
    ),
    _tool("list_transactions", TransactionsArgs, list_transactions, "Lendo suas transações"),
    _tool("get_asset_overview", AssetArgs, asset_overview, "Consultando o mercado"),
    _tool("get_technical_analysis", AnalysisArgs, technical_analysis, "Calculando indicadores"),
    _tool("get_asset_signal", AnalysisArgs, asset_signal, "Consultando o sinal"),
    _tool("list_signals", SignalListArgs, list_signals, "Listando oportunidades"),
    _tool("get_market_overview", NoArgs, market_overview, "Consultando o panorama do mercado"),
    _tool("get_portfolio_risk", RiskArgs, portfolio_risk, "Calculando o risco da carteira"),
    _tool("simulate_scenario", ScenarioArgs, simulate_scenario, "Simulando o cenário"),
    _tool("search_asset", SearchArgs, search_asset, "Buscando o ativo"),
]
TOOLS_BY_NAME = {t.spec.name: t for t in TOOLS}


async def run_tool(
    ctx: ToolContext, name: str, raw_input: Any
) -> tuple[ToolOutput | None, str | None]:
    """Execute a tool call; returns (output, error message for the model)."""
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        return None, f"Ferramenta desconhecida: {name}."
    try:
        args = tool.args.model_validate(raw_input if isinstance(raw_input, dict) else {})
    except ValidationError as exc:
        return None, f"Parâmetros inválidos: {exc.errors()[0]['msg']}."
    try:
        return await tool.handler(ctx, args), None
    except ToolUserError as exc:
        return None, str(exc)
    except AppError as exc:
        return None, exc.message
    except ProviderError:
        return None, "Fonte de dados indisponível no momento."
