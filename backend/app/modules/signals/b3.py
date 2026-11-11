"""Opportunity signals for B3 stocks and FIIs, on the same transparent engine as crypto.

What each analysis covers, and what it does not (shown to the user with every list):

- Stocks: price and volume only. Multiples, statements and dividends are not on the free
  brapi plan, so nothing here says whether a company is cheap or healthy.
- FIIs: the same technical reading plus P/VP and income, which do carry the score. Vacancy,
  property quality and credit risk are not evaluated.

Weights and thresholds are judgement calls that were NOT validated by a backtest: the free plan
has 3 months of history. Treat the score as a reading of conditions, never as an expected return.

Signals are computed once per closed session and stored, so page views cost no brapi requests.
A session only counts as closed once the plan's delay has passed; before that the day's bar is
partial. Strategies stay `is_active=False` and are looked up by key: signals.service picks any
active strategy, so activating these would change the crypto signals.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.modules.market_data import calendars, exchanges
from app.modules.market_data.models import Cryptocurrency, MarketTicker
from app.modules.market_data.providers import brapi
from app.modules.market_data.providers.base import Candle, ProviderError
from app.modules.market_data.providers.brapi import (
    BrapiProvider,
    DailyBar,
    FiiFundamentals,
    FiiPayment,
    ProviderPlanError,
    ProviderRateLimitError,
)
from app.modules.portfolio.schemas import AssetRef
from app.modules.signals import engine, quality
from app.modules.signals.models import AnalysisSignal, SignalStrategy
from app.modules.signals.schemas import (
    COMPONENT_LABELS,
    B3SignalListOut,
    B3SignalOut,
    ComponentOut,
    FiiFundamentalsOut,
    StrategyOut,
)
from app.modules.technical_analysis.service import METHODOLOGY_VERSION, analyze

logger = get_logger(__name__)

AssetType = Literal["STOCK", "FII"]

#: most traded instruments analysed each session; sized to stay well inside the free quota
UNIVERSE = {"STOCK": 40, "FII": 30}
BENCHMARK_SYMBOL = exchanges.REFERENCE_SYMBOL
THRESHOLDS = {"buy": Decimal(65), "sell": Decimal(35)}
STRATEGIES: dict[str, tuple[str, str, dict[str, Decimal]]] = {
    "STOCK": ("voryn-b3-stock", "Voryn B3 Ações v1", dict(engine.DEFAULT_WEIGHTS)),
    "FII": (
        "voryn-b3-fii",
        "Voryn B3 FIIs v1",
        {
            "valuation": Decimal("0.25"),
            "income": Decimal("0.30"),
            "trend": Decimal("0.10"),
            "momentum": Decimal("0.10"),
            "volatility": Decimal("0.10"),
            "volume": Decimal("0.05"),
            "levels": Decimal("0.05"),
            "market": Decimal("0.05"),
        },
    ),
}
DISCLAIMER = (
    "Sinais analíticos gerados por regras a partir de dados com atraso. O score mede o alinhamento "
    "de condições e não é probabilidade de lucro. Os pesos ainda não foram validados por backtest. "
    "Não constituem recomendação de investimento nem consideram seu perfil."
)
SCOPE = {
    "STOCK": (
        "Análise somente técnica, de preço e volume, com até 3 meses de histórico (sem EMA 200). "
        "Não considera balanços, múltiplos nem dividendos: um sinal aqui não diz se a empresa "
        "está barata ou saudável."
    ),
    "FII": (
        "Considera P/VP, rendimentos pagos nos últimos 12 meses e análise técnica. Não avalia "
        "vacância, qualidade dos imóveis, risco de crédito nem a diferença entre fundos de tijolo "
        "e de papel. Sem P/VP e rendimentos não há score: compra e venda ficam suspensas, e o "
        "plano de dados atual libera essas informações para poucos fundos."
    ),
}
#: the NAV is published monthly with a lag; older than this it says little about today
MAX_NAV_AGE_DAYS = 120
MAX_FAILURES_IN_A_ROW = 5


def _pct(value: Decimal, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


# --------------------------------------------------------------------------- FII scoring


def score_valuation(
    price: Decimal, fundamentals: FiiFundamentals | None, today: date
) -> tuple[engine.Component, list[str], str | None, Decimal | None]:
    """P/VP on today's price: brapi's own ratio uses the price of the NAV's reference month.

    1,00 scores 50 and each 0,01 below or above moves it 2 points, capped at 85: a very deep
    discount usually means the market distrusts the assets, so it is not rewarded further.
    """
    nav = fundamentals.nav_per_share if fundamentals else None
    if nav is None or nav <= 0:
        return (
            engine.Component(
                "valuation", Decimal(50), Decimal(0), "Valor patrimonial indisponível."
            ),
            [],
            "Valor patrimonial do fundo indisponível.",
            None,
        )
    ratio = price / nav
    score = max(Decimal(10), min(Decimal(85), 50 + (1 - ratio) * 200))
    as_of = fundamentals.as_of if fundamentals else None
    reference = f" (patrimônio de {as_of:%m/%Y})" if as_of else ""
    detail = f"P/VP de {_pct(ratio, 2)}{reference}."
    risks: list[str] = []
    if ratio < Decimal("0.7"):
        risks.append("Desconto muito grande sobre o patrimônio pode refletir problemas nos ativos.")
    issue = None
    if as_of is None or (today - as_of).days > MAX_NAV_AGE_DAYS:
        issue = "Valor patrimonial do fundo desatualizado ou sem data de referência."
    return engine.Component("valuation", score, Decimal(0), detail), risks, issue, ratio


def score_income(
    price: Decimal,
    fundamentals: FiiFundamentals | None,
    payments: Sequence[FiiPayment],
    today: date,
) -> tuple[engine.Component, list[str], str | None, Decimal | None, int | None]:
    """Yield of what was paid in 12 months, on today's price, discounted when pay is irregular.

    6% scores 30 and 12% scores 80 (capped at 85); each month without a payment takes 5 points.
    Above 16% the score is capped at 60: yields that high are usually non-recurring.
    """
    window = [p for p in payments if today - timedelta(days=365) <= p.payment_date <= today]
    months = len({(p.payment_date.year, p.payment_date.month) for p in window})
    if window:
        dy = sum((p.rate for p in window), Decimal(0)) / price * 100
    elif fundamentals and fundamentals.dividend_yield_12m is not None:
        dy, months = fundamentals.dividend_yield_12m * 100, 0
    else:
        return (
            engine.Component("income", Decimal(50), Decimal(0), "Rendimentos indisponíveis."),
            [],
            "Histórico de rendimentos do fundo indisponível.",
            None,
            None,
        )
    known_months = months if window else None
    score = 30 + (dy - 6) * Decimal(50) / 6
    if known_months is not None:
        score -= (12 - min(known_months, 12)) * 5
    score = max(Decimal(10), min(Decimal(85), score))
    risks: list[str] = []
    if dy > 16:
        score = min(score, Decimal(60))
        risks.append("Rendimento muito alto: pode vir de evento não recorrente.")
    if known_months is not None and known_months < 10:
        risks.append(f"Rendimentos irregulares: pagamentos em {known_months} dos últimos 12 meses.")
    paid = f", com pagamentos em {known_months} dos últimos 12 meses" if known_months else ""
    detail = f"Dividend yield de {_pct(dy)}% em 12 meses sobre o preço atual{paid}."
    return (
        engine.Component("income", score, Decimal(0), detail),
        risks,
        None,
        dy,
        known_months,
    )


# --------------------------------------------------------------------------- generation


def closed_day(now: datetime, delay_seconds: int) -> date:
    """Last session whose final figures are available: the plan's delay must have passed."""
    close = calendars.status("B3", now).last_close
    assert close is not None
    day = close.date()
    if now < close + timedelta(seconds=delay_seconds):
        return calendars.previous_trading_day("B3", day)
    return day


def _candle_time(day: date) -> datetime:
    return datetime.combine(day, time.min, UTC)


def _candles(bars: Sequence[DailyBar], through: date) -> list[Candle]:
    candles = []
    for bar in bars:
        if bar.day > through:
            continue  # the session still in progress: a partial bar never enters a signal
        volume = bar.volume if bar.volume is not None else Decimal(0)
        candles.append(
            Candle(
                open_time=_candle_time(bar.day),
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=volume,
                quote_volume=volume * bar.close,
                closed=True,
            )
        )
    return candles


async def strategy_for(db: AsyncSession, asset_type: str) -> SignalStrategy:
    key, name, weights = STRATEGIES[asset_type]
    strategy = (
        await db.execute(
            select(SignalStrategy)
            .where(SignalStrategy.key == key)
            .order_by(SignalStrategy.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if strategy is None:
        strategy = SignalStrategy(
            key=key,
            version=1,
            name=name,
            weights={k: str(v) for k, v in weights.items()},
            thresholds={k: str(v) for k, v in THRESHOLDS.items()},
            is_active=False,
        )
        db.add(strategy)
        await db.commit()
    return strategy


async def _fii_inputs(
    provider: BrapiProvider, symbol: str
) -> tuple[FiiFundamentals | None, list[FiiPayment], bool]:
    """Missing fundamentals suspend buy/sell through the quality gate; they don't stop the run.

    The last value says the plan refused them: the free plan covers very few FIIs, and asking
    for the dividends of a fund already refused would only waste a request.
    """
    fundamentals: FiiFundamentals | None = None
    payments: list[FiiPayment] = []
    try:
        fundamentals = await provider.fetch_fii_fundamentals(symbol)
    except ProviderRateLimitError:
        raise
    except ProviderPlanError:
        return None, [], True
    except ProviderError as exc:
        logger.warning("fii_fundamentals_unavailable", symbol=symbol, error=str(exc))
    try:
        payments = await provider.fetch_fii_payments(symbol)
    except ProviderRateLimitError:
        raise
    except ProviderError as exc:
        logger.warning("fii_payments_unavailable", symbol=symbol, error=str(exc))
    return fundamentals, payments, False


async def _generate_one(
    db: AsyncSession,
    provider: BrapiProvider,
    instrument: Cryptocurrency,
    ticker: MarketTicker,
    strategy: SignalStrategy,
    context: engine.MarketContext,
    through: date,
    history_range: str,
    now: datetime,
    max_quote_age: timedelta,
) -> bool:
    bars = await provider.fetch_daily_history(instrument.symbol, history_range)
    closed = _candles(bars, through)
    result = analyze(closed, "1d")
    if not closed or result.snapshot is None or result.trend is None:
        logger.info("b3_signal_skipped", symbol=instrument.symbol, candles=len(closed))
        return False
    is_stale = closed[-1].open_time < _candle_time(through)
    report = quality.assess(
        closed=closed,
        snapshot=result.snapshot,
        timeframe="1d",
        is_stale=is_stale,
        quote_price=ticker.price,
        quote_fetched_at=ticker.fetched_at,
        now=now,
        quote_max_age=max_quote_age,
        reference_source="catálogo da brapi",
    )

    extra: list[engine.Component] = []
    extra_risks: list[str] = []
    indicators = result.snapshot.model_dump(mode="json")
    if instrument.asset_type == "FII":
        fundamentals, payments, plan_denied = await _fii_inputs(provider, instrument.symbol)
        today = now.date()
        valuation, risks_v, issue_v, ratio = score_valuation(ticker.price, fundamentals, today)
        income, risks_i, issue_i, dy, months = score_income(
            ticker.price, fundamentals, payments, today
        )
        extra, extra_risks = [valuation, income], [*risks_v, *risks_i]
        if plan_denied:
            report.flag("incomplete", "P/VP e rendimentos deste fundo não estão no plano de dados.")
        else:
            for issue in (issue_v, issue_i):
                if issue:
                    report.flag("incomplete", issue)
        last_payment = max(payments, key=lambda p: p.payment_date, default=None)
        indicators["fundamentals"] = {
            "price_to_nav": str(ratio) if ratio is not None else None,
            "nav_per_share": (
                str(fundamentals.nav_per_share)
                if fundamentals and fundamentals.nav_per_share is not None
                else None
            ),
            "nav_as_of": (
                fundamentals.as_of.isoformat() if fundamentals and fundamentals.as_of else None
            ),
            "dividend_yield_12m": str(dy) if dy is not None else None,
            "months_paid_12m": months,
            "last_payment_rate": str(last_payment.rate) if last_payment else None,
            "last_payment_date": last_payment.payment_date.isoformat() if last_payment else None,
            "segment": fundamentals.segment if fundamentals else None,
        }

    weights = {k: Decimal(str(v)) for k, v in strategy.weights.items()}
    thresholds = {k: Decimal(str(v)) for k, v in strategy.thresholds.items()}
    last = closed[-1]
    signal = engine.evaluate(
        snapshot=result.snapshot,
        trend=result.trend,
        supports=result.supports,
        resistances=result.resistances,
        bandwidth_percentile=result.bandwidth_percentile,
        last_candle_up=last.close >= last.open,
        market=context,
        stale=is_stale,
        weights=weights,
        thresholds=thresholds,
        quality_issue=None if report.status in ("valid", "stale") else " ".join(report.reasons),
        volatility_window=min(100, max(len(closed) - 19, 1)),
        currency="R$",
        extra=extra,
        extra_risks=extra_risks,
    )
    await db.execute(
        insert(AnalysisSignal)
        .values(
            cryptocurrency_id=instrument.id,
            timeframe="1d",
            strategy_id=strategy.id,
            candle_time=last.open_time,
            reference_price=last.close,
            score=signal.score,
            classification=signal.classification,
            components=[
                {"key": c.key, "score": str(c.score), "weight": str(c.weight), "detail": c.detail}
                for c in signal.components
            ],
            indicators=indicators,
            trend=result.trend.classification,
            justification=signal.justification,
            risks=signal.risks,
            invalidation=signal.invalidation,
            data_source=f"{brapi.SOURCE}:{instrument.symbol}",
            data_fetched_at=now,
            data_is_stale=is_stale,
            data_quality=report.status,
            quality_reasons=report.reasons,
            methodology_version=METHODOLOGY_VERSION,
        )
        .on_conflict_do_nothing()
    )
    await db.commit()
    return True


async def _already_done(
    db: AsyncSession, strategy: SignalStrategy, ids: Sequence[uuid.UUID], candle: datetime
) -> set[uuid.UUID]:
    rows = await db.execute(
        select(AnalysisSignal.cryptocurrency_id).where(
            AnalysisSignal.strategy_id == strategy.id,
            AnalysisSignal.timeframe == "1d",
            AnalysisSignal.candle_time == candle,
            AnalysisSignal.cryptocurrency_id.in_(list(ids)),
        )
    )
    return set(rows.scalars())


async def generate(db: AsyncSession, provider: BrapiProvider) -> int:
    """One signal per instrument for the last closed session; re-runs cost no requests."""
    exchanges.ensure_enabled("B3")
    settings = get_settings()
    now = exchanges.utcnow()
    delay = brapi.DELAY_SECONDS[settings.brapi_plan]
    through = closed_day(now, delay)
    candle = _candle_time(through)
    history_range = brapi.HISTORY_RANGES[settings.brapi_plan][-1]
    max_quote_age = timedelta(seconds=delay + 2 * settings.b3_sync_interval_seconds)

    work: list[tuple[Cryptocurrency, MarketTicker, SignalStrategy]] = []
    for asset_type, size in UNIVERSE.items():
        strategy = await strategy_for(db, asset_type)
        rows = await exchanges.most_traded(db, "B3", asset_type, size)
        done = await _already_done(db, strategy, [r[0].id for r in rows], candle)
        work += [(i, t, strategy) for i, t in rows if i.id not in done]
    if not work:
        return 0
    if await exchanges.blocked_for() or await exchanges.quota_reached(now):
        logger.warning("b3_signals_postponed", pending=len(work))
        return 0

    produced, failures = 0, 0
    try:
        breadth = await exchanges.breadth_pct(db, "B3")
        benchmark_trend: str | None = None
        try:
            bars = await provider.fetch_daily_history(BENCHMARK_SYMBOL, history_range)
            benchmark = analyze(_candles(bars, through), "1d")
            benchmark_trend = benchmark.trend.classification if benchmark.trend else None
        except ProviderRateLimitError:
            raise
        except ProviderError as exc:
            logger.warning("b3_benchmark_unavailable", error=str(exc))
        context = engine.MarketContext(
            breadth,
            benchmark_trend,
            benchmark="Ibovespa (via BOVA11)",
            breadth_period="no último pregão",
        )
        for instrument, ticker, strategy in work:
            try:
                if await _generate_one(
                    db,
                    provider,
                    instrument,
                    ticker,
                    strategy,
                    context,
                    through,
                    history_range,
                    now,
                    max_quote_age,
                ):
                    produced += 1
                failures = 0
            except ProviderRateLimitError:
                raise
            except ProviderError as exc:
                failures += 1
                logger.warning("b3_signal_failed", symbol=instrument.symbol, error=str(exc))
                if failures >= MAX_FAILURES_IN_A_ROW:
                    logger.error("b3_signals_aborted", produced=produced)
                    break
    except ProviderRateLimitError as exc:
        logger.warning("b3_signals_rate_limited", retry_after=exc.retry_after, produced=produced)
        await exchanges.block(exc.retry_after)
    await exchanges.record_usage(provider.requests, now)
    logger.info("b3_signals_generated", produced=produced, requests=provider.requests)
    return produced


# --------------------------------------------------------------------------- reading


def _strategy_out(strategy: SignalStrategy) -> StrategyOut:
    weights = {k: Decimal(str(v)) for k, v in strategy.weights.items()}
    total = sum(weights.values())
    return StrategyOut(
        key=strategy.key,
        version=strategy.version,
        name=strategy.name,
        weights_pct={k: (w / total * 100).quantize(Decimal("0.1")) for k, w in weights.items()},
        buy_threshold=Decimal(str(strategy.thresholds["buy"])),
        sell_threshold=Decimal(str(strategy.thresholds["sell"])),
    )


def _is_current(candle_time: datetime, now: datetime) -> bool:
    delay = brapi.DELAY_SECONDS[get_settings().brapi_plan]
    latest = closed_day(now, delay)
    return candle_time.date() >= calendars.previous_trading_day("B3", latest)


def _to_out(
    signal: AnalysisSignal,
    instrument: Cryptocurrency,
    ticker: MarketTicker | None,
    strategy: SignalStrategy,
    now: datetime,
) -> B3SignalOut:
    fundamentals = signal.indicators.get("fundamentals")
    return B3SignalOut(
        id=signal.id,
        asset=AssetRef(
            id=instrument.id,
            slug=instrument.symbol,
            symbol=instrument.symbol,
            name=instrument.name,
            image_url=instrument.image_url,
        ),
        timeframe="1d",
        candle_time=signal.candle_time,
        generated_at=signal.generated_at,
        reference_price=signal.reference_price,
        current_price=ticker.price if ticker else None,
        score=signal.score,
        classification=signal.classification,
        trend=signal.trend,
        components=[
            ComponentOut(
                key=c["key"],
                label=COMPONENT_LABELS.get(c["key"], c["key"]),
                score=Decimal(c["score"]),
                weight_pct=(Decimal(c["weight"]) * 100).quantize(Decimal("0.1")),
                detail=c["detail"],
            )
            for c in signal.components
        ],
        justification=signal.justification,
        risks=signal.risks,
        invalidation=signal.invalidation,
        indicators=signal.indicators,
        data_source=signal.data_source,
        data_fetched_at=signal.data_fetched_at,
        data_is_stale=signal.data_is_stale,
        data_quality=signal.data_quality,
        quality_reasons=signal.quality_reasons,
        is_current=_is_current(signal.candle_time, now),
        strategy_key=strategy.key,
        strategy_version=strategy.version,
        methodology_version=signal.methodology_version,
        asset_type=instrument.asset_type,
        sector=instrument.sector,
        currency=instrument.currency,
        fundamentals=FiiFundamentalsOut(**fundamentals) if fundamentals else None,
        scope=SCOPE[instrument.asset_type],
    )


async def list_signals(
    db: AsyncSession, asset_type: AssetType, limit: int = UNIVERSE["STOCK"]
) -> B3SignalListOut:
    now = exchanges.utcnow()
    strategy = await strategy_for(db, asset_type)
    latest = (
        select(AnalysisSignal)
        .where(AnalysisSignal.strategy_id == strategy.id, AnalysisSignal.timeframe == "1d")
        .ext(distinct_on(AnalysisSignal.cryptocurrency_id))
        .order_by(AnalysisSignal.cryptocurrency_id, AnalysisSignal.candle_time.desc())
        .subquery()
    )
    rows = (
        await db.execute(
            select(AnalysisSignal, Cryptocurrency, MarketTicker)
            .join(latest, AnalysisSignal.id == latest.c.id)
            .join(Cryptocurrency, Cryptocurrency.id == AnalysisSignal.cryptocurrency_id)
            .outerjoin(
                MarketTicker,
                (MarketTicker.cryptocurrency_id == Cryptocurrency.id)
                & (MarketTicker.quote_currency == Cryptocurrency.currency),
            )
            .where(
                Cryptocurrency.market == "B3",
                Cryptocurrency.asset_type == asset_type,
                Cryptocurrency.is_active.is_(True),
            )
            .order_by(AnalysisSignal.score.desc(), Cryptocurrency.symbol)
        )
    ).all()
    # An old signal does not describe today's market, so it never appears in the ranking; and a
    # score held back by missing data never ranks above one built on complete data.
    items = sorted(
        (
            _to_out(signal, instrument, ticker, strategy, now)
            for signal, instrument, ticker in rows
            if _is_current(signal.candle_time, now)
        ),
        key=lambda s: (s.data_quality != "valid", -s.score),
    )
    return B3SignalListOut(
        items=items[:limit],
        asset_type=asset_type,
        strategy=_strategy_out(strategy),
        disclaimer=DISCLAIMER,
        scope=SCOPE[asset_type],
        status=await exchanges.market_status(db, "B3"),
    )


async def for_asset(db: AsyncSession, symbol: str) -> B3SignalOut:
    now = exchanges.utcnow()
    instrument, ticker = await exchanges.instrument(db, "B3", symbol)
    if instrument.asset_type not in STRATEGIES:
        raise NotFoundError(
            "Este tipo de ativo ainda não recebe sinais.", code="signal_unavailable"
        )
    strategy = await strategy_for(db, instrument.asset_type)
    signal = (
        await db.execute(
            select(AnalysisSignal)
            .where(
                AnalysisSignal.cryptocurrency_id == instrument.id,
                AnalysisSignal.strategy_id == strategy.id,
                AnalysisSignal.timeframe == "1d",
            )
            .order_by(AnalysisSignal.candle_time.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if signal is None:
        raise NotFoundError(
            "Este ativo está fora dos mais negociados analisados por sessão.",
            code="signal_unavailable",
        )
    return _to_out(signal, instrument, ticker, strategy, now)
