"""Backtest runs: validation, queueing, execution in the worker and read models."""

import math
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.errors import AppError, NotFoundError
from app.core.logging import get_logger
from app.core.tasks import enqueue
from app.modules.backtesting import engine as bt
from app.modules.backtesting.models import BacktestRun
from app.modules.backtesting.schemas import (
    BacktestIn,
    BacktestOut,
    BacktestResultOut,
    BacktestSummaryOut,
    EquityPointOut,
    GridRowOut,
    MetricsOut,
    ParamSpecOut,
    SegmentOut,
    StrategyInfoOut,
    TradeOut,
)
from app.modules.backtesting.strategies import VorynSignal
from app.modules.market_data import candles as candle_service
from app.modules.market_data import service as market
from app.modules.market_data.models import Cryptocurrency
from app.modules.market_data.providers.base import Candle, CandleProvider, Timeframe
from app.modules.portfolio.insights import STABLECOINS
from app.modules.portfolio.service import _asset_ref
from app.modules.signals import service as signals

logger = get_logger(__name__)

ENGINE_VERSION = "bt-1"
TASK = "backtests.run"
CANDLES = 1000
MIN_TEST_BARS = 60
RUNS_PER_HOUR = 10
KEEP_RUNS = 30
STUCK_AFTER = timedelta(minutes=15)
MAX_EQUITY_POINTS = 500
MAX_TRADES = 300


def _spec(
    key: str, label: str, default: int, bounds: tuple[int, int], grid: list[int]
) -> ParamSpecOut:
    return ParamSpecOut(
        key=key, label=label, default=default, min=bounds[0], max=bounds[1], grid=grid
    )


PARAMS: dict[str, list[ParamSpecOut]] = {
    "ema_cross": [
        _spec("fast", "EMA rápida", 12, (2, 100), [9, 12, 20]),
        _spec("slow", "EMA lenta", 50, (5, 200), [26, 50, 100]),
    ],
    "rsi_reversion": [
        _spec("low", "Compra com RSI abaixo de", 30, (5, 50), [25, 30, 35]),
        _spec("high", "Venda com RSI acima de", 70, (50, 95), [65, 70, 75]),
    ],
}

CATALOGUE = [
    StrategyInfoOut(
        key="voryn_signal",
        label="Sinais Voryn (voryn-core)",
        description="Compra quando o sinal da plataforma indica potencial de compra e vende em "
        "potencial de venda; mantém a posição nos demais casos.",
        params=[],
        optimizable=False,
    ),
    StrategyInfoOut(
        key="ema_cross",
        label="Cruzamento de médias (EMA)",
        description="Comprado enquanto a média exponencial rápida está acima da lenta.",
        params=PARAMS["ema_cross"],
        optimizable=True,
    ),
    StrategyInfoOut(
        key="rsi_reversion",
        label="Reversão por RSI",
        description="Compra quando o RSI(14) cai abaixo do limiar inferior e vende quando passa "
        "do superior.",
        params=PARAMS["rsi_reversion"],
        optimizable=True,
    ),
    StrategyInfoOut(
        key="buy_and_hold",
        label="Comprar e manter",
        description="Referência: compra no início do período e mantém até o fim.",
        params=[],
        optimizable=False,
    ),
]


class BacktestInputError(AppError):
    status_code = 422
    code = "backtest_invalid"


def utcnow() -> datetime:
    return datetime.now(UTC)


def _param_values(strategy: str, params: dict[str, int]) -> dict[str, int]:
    specs = PARAMS.get(strategy, [])
    unknown = set(params) - {p.key for p in specs}
    if unknown:
        raise BacktestInputError(f"Parâmetro não reconhecido: {', '.join(sorted(unknown))}.")
    values = {}
    for spec in specs:
        value = params.get(spec.key, spec.default)
        if not spec.min <= value <= spec.max:
            raise BacktestInputError(f"{spec.label} deve estar entre {spec.min} e {spec.max}.")
        values[spec.key] = value
    return values


def _factory(strategy: str) -> Callable[[dict[str, int]], bt.Strategy]:
    if strategy == "ema_cross":
        return lambda p: bt.EmaCross(p["fast"], p["slow"])
    if strategy == "rsi_reversion":
        return lambda p: bt.RsiReversion(p["low"], p["high"])
    return lambda _: bt.BuyAndHold()


def _build(strategy: str, params: dict[str, int]) -> bt.Strategy:
    try:
        return _factory(strategy)(params)
    except ValueError as exc:
        raise BacktestInputError(str(exc)) from None


# --------------------------------------------------------------------------- requests


async def create_run(db: AsyncSession, user_id: uuid.UUID, body: BacktestIn) -> BacktestRun:
    crypto = await db.get(Cryptocurrency, body.asset_id)
    if crypto is None:
        raise NotFoundError("Ativo não encontrado.")
    if crypto.symbol.upper() in STABLECOINS:
        raise BacktestInputError("Stablecoins não têm variação de preço para testar.")
    params = _param_values(body.strategy, body.params)
    if body.strategy in PARAMS:
        _build(body.strategy, params)
    await rate_limit.enforce(f"backtests:hour:{user_id}", RUNS_PER_HOUR, 3600)

    run = BacktestRun(
        user_id=user_id,
        cryptocurrency_id=crypto.id,
        timeframe=body.timeframe,
        strategy=body.strategy,
        params=params,
        optimize=body.optimize and body.strategy in PARAMS,
        fee_bps=body.fee_bps,
        slippage_bps=body.slippage_bps,
        train_pct=body.train_pct,
        engine_version=ENGINE_VERSION,
    )
    db.add(run)
    await db.flush()
    keep = select(BacktestRun.id).where(BacktestRun.user_id == user_id)
    keep = keep.order_by(BacktestRun.created_at.desc()).limit(KEEP_RUNS)
    await db.execute(
        delete(BacktestRun).where(BacktestRun.user_id == user_id, BacktestRun.id.not_in(keep))
    )
    await db.commit()
    await enqueue(TASK, str(run.id))
    return run


async def get_owned(db: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> BacktestRun:
    run = await db.get(BacktestRun, run_id)
    if run is None or run.user_id != user_id:
        raise NotFoundError("Backtest não encontrado.")
    if run.status in ("queued", "running") and utcnow() - run.created_at > STUCK_AFTER:
        run.status, run.error = "failed", "O processamento excedeu o tempo limite. Tente de novo."
        run.finished_at = utcnow()
        await db.commit()
    return run


async def list_runs(db: AsyncSession, user_id: uuid.UUID) -> list[BacktestRun]:
    rows = await db.execute(
        select(BacktestRun)
        .where(BacktestRun.user_id == user_id)
        .order_by(BacktestRun.created_at.desc())
        .limit(KEEP_RUNS)
    )
    return list(rows.scalars())


async def delete_run(db: AsyncSession, run: BacktestRun) -> None:
    await db.delete(run)
    await db.commit()


async def summaries(db: AsyncSession, runs: Sequence[BacktestRun]) -> list[BacktestSummaryOut]:
    cryptos = await market.cryptos_by_id(db, list({r.cryptocurrency_id for r in runs}))
    out = []
    for r in runs:
        validation = (r.result or {}).get("validation") or {}
        out.append(
            BacktestSummaryOut(
                id=r.id,
                asset=_asset_ref(cryptos[r.cryptocurrency_id]),
                timeframe=r.timeframe,
                strategy=r.strategy,
                status=r.status,
                validation_return_pct=(validation.get("strategy") or {}).get("total_return_pct"),
                benchmark_return_pct=(validation.get("benchmark") or {}).get("total_return_pct"),
                created_at=r.created_at,
                finished_at=r.finished_at,
            )
        )
    return out


async def detail(db: AsyncSession, run: BacktestRun) -> BacktestOut:
    (summary,) = await summaries(db, [run])
    return BacktestOut(
        **summary.model_dump(),
        params=run.params,
        optimize=run.optimize,
        fee_bps=run.fee_bps,
        slippage_bps=run.slippage_bps,
        train_pct=run.train_pct,
        engine_version=run.engine_version,
        error=run.error,
        result=BacktestResultOut.model_validate(run.result) if run.result else None,
    )


# --------------------------------------------------------------------------- execution


def _metrics_out(m: bt.Metrics) -> MetricsOut:
    def q(v: Decimal | None, step: str = "0.01") -> Decimal | None:
        return v.quantize(Decimal(step)) if v is not None else None

    return MetricsOut(
        start=m.start,
        end=m.end,
        bars=m.bars,
        final_equity=m.final_equity.quantize(Decimal("0.01")),
        total_return_pct=m.total_return_pct.quantize(Decimal("0.01")),
        cagr_pct=q(m.cagr_pct),
        max_drawdown_pct=m.max_drawdown_pct.quantize(Decimal("0.01")),
        volatility_pct=q(m.volatility_pct),
        sharpe=q(m.sharpe),
        trades=m.trades,
        win_rate_pct=q(m.win_rate_pct),
        avg_trade_pct=q(m.avg_trade_pct),
        exposure_pct=m.exposure_pct.quantize(Decimal("0.01")),
        fees=m.fees.quantize(Decimal("0.01")),
    )


def backtest(
    candles: Sequence[Candle],
    timeframe: Timeframe,
    make: Callable[[dict[str, int]], bt.Strategy],
    params: dict[str, int],
    grid: list[dict[str, int]],
    costs: bt.Costs,
    train_pct: int,
) -> dict[str, Any]:
    """Pure backtest of one strategy family: optimize on train (if a grid is given), then
    validate once. Returns the JSON-ready result body (without data provenance)."""
    candidates = [make(p) for p in (grid or [params])]
    start = max(s.warmup for s in candidates)
    n = len(candles)
    split = start + (n - start) * train_pct // 100
    if split - start < MIN_TEST_BARS or n - split < MIN_TEST_BARS:
        raise BacktestInputError(
            "Histórico insuficiente para separar treino e validação com pelo menos "
            f"{MIN_TEST_BARS} candles em cada parte."
        )

    def train_run(strategy: bt.Strategy) -> tuple[bt.Run, bt.Metrics]:
        strategy.prepare(candles)
        run = bt.simulate(candles, strategy, start, split, costs)
        return run, bt.metrics(run, timeframe)

    scored = [(s, *train_run(s)) for s in candidates]
    best = max(
        scored,
        key=lambda x: (
            x[2].sharpe if x[2].sharpe is not None else Decimal("-Infinity"),
            x[2].total_return_pct,
        ),
    )
    chosen, train, train_metrics = best
    validation = bt.simulate(candles, chosen, split, n, costs)
    hold = bt.BuyAndHold()
    hold_train = bt.simulate(candles, hold, start, split, costs)
    hold_validation = bt.simulate(candles, hold, split, n, costs)

    equity: list[EquityPointOut] = []
    for segment, run, bench in (
        ("train", train, hold_train),
        ("validation", validation, hold_validation),
    ):
        for (t, value), (_, b) in zip(run.equity, bench.equity, strict=True):
            equity.append(
                EquityPointOut(
                    time=t,
                    segment=segment,
                    strategy=value.quantize(Decimal("0.01")),
                    benchmark=b.quantize(Decimal("0.01")),
                )
            )
    step = max(1, math.ceil(len(equity) / MAX_EQUITY_POINTS))
    sampled = [p for i, p in enumerate(equity) if i % step == 0 or i == len(equity) - 1]

    def trades(run: bt.Run, segment: str) -> list[TradeOut]:
        return [
            TradeOut(
                segment=segment,
                entry_time=t.entry_time,
                entry_price=t.entry_price.quantize(Decimal("0.00000001")),
                exit_time=t.exit_time,
                exit_price=t.exit_price.quantize(Decimal("0.00000001")) if t.exit_price else None,
                return_pct=_q2(t.return_pct),
            )
            for t in run.trades
        ]

    return {
        "selected_params": chosen.params(),
        "grid": [
            GridRowOut(
                params=s.params(),
                train_sharpe=m.sharpe.quantize(Decimal("0.01")) if m.sharpe is not None else None,
                train_return_pct=m.total_return_pct.quantize(Decimal("0.01")),
                selected=s is chosen,
            ).model_dump(mode="json")
            for s, _, m in scored
        ]
        if grid
        else [],
        "train": SegmentOut(
            strategy=_metrics_out(train_metrics),
            benchmark=_metrics_out(bt.metrics(hold_train, timeframe)),
        ).model_dump(mode="json"),
        "validation": SegmentOut(
            strategy=_metrics_out(bt.metrics(validation, timeframe)),
            benchmark=_metrics_out(bt.metrics(hold_validation, timeframe)),
        ).model_dump(mode="json"),
        "equity": [p.model_dump(mode="json") for p in sampled],
        "trades": [
            t.model_dump(mode="json")
            for t in (trades(train, "train") + trades(validation, "validation"))[-MAX_TRADES:]
        ],
        "initial_capital": str(bt.INITIAL_CAPITAL),
        "candles": n,
        "warmup": start,
        "first_candle": candles[0].open_time.isoformat(),
        "last_candle": candles[-1].open_time.isoformat(),
        "split_at": candles[split].open_time.isoformat(),
    }


def _notes(run: BacktestRun) -> list[str]:
    notes = [
        "Decisão no fechamento de cada candle, execução na abertura do candle seguinte "
        "(sem uso de dados futuros).",
        f"Custos por operação: taxa de {run.fee_bps / 100:.2f}% e slippage de "
        f"{run.slippage_bps / 100:.2f}% no preço.".replace(".", ","),
        "Sempre 100% comprado ou 100% fora; sem alavancagem, sem venda a descoberto; capital "
        "parado não rende.",
        f"Treino: primeiros {run.train_pct}% do histórico útil. Validação: o restante, "
        "executada uma única vez a partir de posição zerada.",
    ]
    if run.optimize:
        notes.append(
            "Parâmetros escolhidos pelo maior Sharpe no treino; compare treino e validação "
            "para avaliar sobreajuste."
        )
    if run.strategy == "voryn_signal":
        notes.append(
            "A amplitude de mercado não é armazenada historicamente; o componente de mercado "
            "do sinal usa apenas a tendência do Bitcoin no mesmo candle."
        )
    notes.append("Resultados passados não garantem resultados futuros.")
    return notes


async def _closed_candles(
    db: AsyncSession, crypto: Cryptocurrency, timeframe: Timeframe, provider: CandleProvider
) -> tuple[list[Candle], candle_service.CandleSet]:
    candle_set = await candle_service.get_candles(db, crypto, timeframe, provider, CANDLES)
    return [c for c in candle_set.candles if c.closed], candle_set


async def execute(db: AsyncSession, run_id: uuid.UUID, provider: CandleProvider) -> None:
    run = await db.get(BacktestRun, run_id)
    if run is None or run.status != "queued":
        return
    run.status = "running"
    await db.commit()
    try:
        crypto = await db.get(Cryptocurrency, run.cryptocurrency_id)
        assert crypto is not None
        timeframe: Timeframe = run.timeframe  # type: ignore[assignment]
        candles, candle_set = await _closed_candles(db, crypto, timeframe, provider)
        costs = bt.Costs(Decimal(run.fee_bps), Decimal(run.slippage_bps))
        if run.strategy == "voryn_signal":
            strategy_row = await signals.active_strategy(db)
            weights, thresholds = signals.strategy_params(strategy_row)
            btc_candles = None
            if crypto.source_id != "bitcoin":
                btc = await market.resolve_asset(db, "bitcoin")
                if btc is not None:
                    btc_candles = (await _closed_candles(db, btc, timeframe, provider))[0]
            strategy = VorynSignal(
                timeframe, weights, thresholds, strategy_row.version, btc_candles
            )
            body = backtest(candles, timeframe, lambda _: strategy, {}, [], costs, run.train_pct)
        else:
            grid: list[dict[str, int]] = []
            if run.optimize:
                specs = PARAMS[run.strategy]
                grid = [{}]
                for spec in specs:
                    grid = [{**g, spec.key: v} for g in grid for v in spec.grid]
                grid = [g for g in grid if _valid(run.strategy, g)]
            body = backtest(
                candles, timeframe, _factory(run.strategy), run.params, grid, costs, run.train_pct
            )
        body.update(
            quote="USDT",
            data_source=f"{candle_set.source}:{candle_set.pair}",
            data_fetched_at=candle_set.fetched_at.isoformat(),
            notes=_notes(run),
        )
        run.result = BacktestResultOut.model_validate(body).model_dump(mode="json")
        run.status = "done"
    except Exception as exc:
        if not isinstance(exc, AppError):
            logger.exception("backtest_failed", run_id=str(run_id))
        await db.rollback()
        failed = await db.get(BacktestRun, run_id)
        if failed is None:
            return
        failed.status = "failed"
        failed.error = (
            exc.message if isinstance(exc, AppError) else "Não foi possível concluir o backtest."
        )
        failed.finished_at = utcnow()
        await db.commit()
        return
    run.finished_at = utcnow()
    await db.commit()


def _q2(value: Decimal | None) -> Decimal | None:
    return value.quantize(Decimal("0.01")) if value is not None else None


def _valid(strategy: str, params: dict[str, int]) -> bool:
    try:
        _factory(strategy)(params)
    except ValueError:
        return False
    return True
