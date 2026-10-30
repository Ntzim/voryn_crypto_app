"""Portfolio risk: today's holdings measured against their own daily price history.

Everything describes what the user holds now, not their past trading. Return statistics
use today's weights held constant; path statistics (drawdown, stress windows) value
today's quantities at each past close. Amounts apply percentages to today's covered
market value in the reporting currency.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.market_data import candles as candle_service
from app.modules.market_data import service as market
from app.modules.market_data.models import Cryptocurrency
from app.modules.market_data.providers.base import CandleProvider
from app.modules.portfolio import service as portfolio_service
from app.modules.portfolio.insights import STABLECOINS
from app.modules.portfolio.models import Portfolio
from app.modules.portfolio.schemas import Currency, PositionOut, SummaryOut
from app.modules.risk import metrics as m
from app.modules.risk.scenario import Exposure, simulate
from app.modules.risk.schemas import (
    AssetRiskOut,
    ConcentrationOut,
    CorrelationOut,
    DrawdownOut,
    Liquidity,
    RiskFlagOut,
    RiskOut,
    RiskWindow,
    ScenarioIn,
    ScenarioLineOut,
    ScenarioOut,
    StressWindowOut,
    VarOut,
)
from app.modules.signals.service import looks_pegged

ZERO = Decimal(0)
HUNDRED = Decimal(100)
PCT = Decimal("0.01")
RATIO = Decimal("0.01")
VAR_LEVELS = (Decimal("0.95"), Decimal("0.99"))
STRESS_DAYS = (7, 30)
CORRELATION_TOP = 8
ADV_DAYS = 30
#: position ÷ average daily volume: up to 1% is liquid, up to 10% needs care.
LIQUIDITY_HIGH, LIQUIDITY_MEDIUM = Decimal(1), Decimal(10)
DATA_SOURCE = "Binance (dados públicos) · candles diários fechados (UTC), par USDT"
METHODOLOGY = [
    "Tudo descreve a carteira de hoje sobre o histórico de preços, não o seu histórico de "
    "operações.",
    "Volatilidade, VaR, beta e contribuição ao risco: retornos diários simples com os pesos "
    "atuais mantidos constantes; volatilidade = desvio-padrão amostral × √365 (cripto negocia "
    "todos os dias).",
    "Drawdown e piores janelas (1, 7 e 30 dias): as quantidades atuais avaliadas a cada "
    "fechamento diário do período.",
    "VaR histórico de 1 dia: perda do percentil empírico (95% e 99%), sem interpolação. "
    "Expected shortfall: perda média nos dias além do VaR 95%.",
    "Beta e correlação calculados sobre os dias em comum entre as séries. Mínimo de 30 "
    "observações; abaixo disso a métrica não é exibida.",
    "Stablecoins: valor constante de US$ 1 (risco de emissor não modelado).",
    "Liquidez: valor da posição ÷ volume médio diário de 30 dias no par USDT da Binance "
    "(uma única corretora; o volume global é maior).",
]


def utcnow() -> datetime:
    return datetime.now(UTC)


def _q(value: Decimal | None, step: Decimal = PCT) -> Decimal | None:
    return value.quantize(step) if value is not None else None


@dataclass
class _Asset:
    position: PositionOut
    crypto: Cryptocurrency
    value_usd: Decimal
    stablecoin: bool
    #: closed daily closes (USD) by day, within the window; None when unavailable
    closes: dict[date, Decimal] | None = None
    volumes: list[Decimal] = field(default_factory=list)


@dataclass
class _RiskData:
    summary: SummaryOut
    assets: list[_Asset]
    btc: dict[date, Decimal] | None
    fetched_at: datetime | None


async def _closes(
    db: AsyncSession, crypto: Cryptocurrency, provider: CandleProvider, window: int
) -> tuple[dict[date, Decimal], list[Decimal], datetime] | None:
    try:
        candle_set = await candle_service.get_candles(db, crypto, "1d", provider)
    except AppError:
        return None
    closed = [c for c in candle_set.candles if c.closed][-(window + 1) :]
    if not closed:
        return None
    closes = {c.open_time.date(): c.close for c in closed}
    return closes, [c.quote_volume for c in closed[-ADV_DAYS:]], candle_set.fetched_at


async def _collect(
    db: AsyncSession,
    portfolio: Portfolio,
    currency: Currency,
    window: int,
    provider: CandleProvider,
) -> _RiskData:
    summary = await portfolio_service.summary(db, portfolio, currency)
    cryptos = await market.cryptos_by_id(db, [p.asset.id for p in summary.positions])
    to_usd = Decimal(1) if currency == "USD" else Decimal(1) / (summary.fx_usd_brl or Decimal(1))
    fetched: list[datetime] = []
    assets: list[_Asset] = []
    for p in summary.positions:
        crypto = cryptos[p.asset.id]
        asset = _Asset(p, crypto, p.market_value * to_usd, p.asset.symbol in STABLECOINS)
        if not asset.stablecoin:
            got = await _closes(db, crypto, provider, window)
            if got is not None:
                asset.closes, asset.volumes, at = got
                fetched.append(at)
                series = list(asset.closes.values())
                vol = m.annualized_volatility_pct(m.simple_returns(series))
                asset.stablecoin = looks_pegged(series[-1], vol)
        assets.append(asset)

    btc_closes = next(
        (a.closes for a in assets if a.crypto.source_id == "bitcoin" and a.closes), None
    )
    if btc_closes is None:
        btc = await market.resolve_asset(db, "bitcoin")
        got = await _closes(db, btc, provider, window) if btc is not None else None
        btc_closes = got[0] if got else None
    return _RiskData(summary, assets, btc_closes, min(fetched) if fetched else None)


def _paired_returns(
    a: dict[date, Decimal], b: dict[date, Decimal]
) -> tuple[list[Decimal], list[Decimal]]:
    _, series = m.aligned({"a": a, "b": b})
    return m.simple_returns(series["a"]), m.simple_returns(series["b"])


def _liquidity(position_to_volume: Decimal | None) -> Liquidity:
    if position_to_volume is None:
        return "unknown"
    if position_to_volume <= LIQUIDITY_HIGH:
        return "high"
    return "medium" if position_to_volume <= LIQUIDITY_MEDIUM else "low"


def _pct_text(value: Decimal, digits: int = 0) -> str:
    return f"{value:.{digits}f}".replace(".", ",") + "%"


async def portfolio_risk(
    db: AsyncSession,
    portfolio: Portfolio,
    currency: Currency,
    window: RiskWindow,
    provider: CandleProvider,
) -> RiskOut:
    data = await _collect(db, portfolio, currency, window, provider)
    now = utcnow()
    total = data.summary.market_value
    priced = [a for a in data.assets if a.stablecoin or a.closes]
    uncovered = [a for a in data.assets if not a.stablecoin and not a.closes]
    covered_value = sum((a.position.market_value for a in priced), ZERO)

    # Holdings-based value series (USD) over the days every priced, non-pegged asset traded.
    moving = [a for a in priced if not a.stablecoin and a.closes]
    days, aligned = m.aligned({a.crypto.source_id: a.closes or {} for a in moving})
    stable_usd = sum((a.value_usd for a in priced if a.stablecoin), ZERO)
    if moving:
        values = [
            (
                day,
                stable_usd
                + sum((a.position.quantity * aligned[a.crypto.source_id][i] for a in moving), ZERO),
            )
            for i, day in enumerate(days)
        ]
    else:
        values = []
    # Return statistics use today's weights held constant (so risk contributions add up to
    # 100%); drawdown and stress windows follow the value path of today's quantities.
    asset_returns = {key: m.simple_returns(closes) for key, closes in aligned.items()}
    weight_of = {
        a.crypto.source_id: a.position.market_value / covered_value if covered_value else ZERO
        for a in moving
    }
    port_returns = [
        sum((weight_of[key] * rets[t] for key, rets in asset_returns.items()), ZERO)
        for t in range(max(len(days) - 1, 0))
    ]
    enough = len(port_returns) >= m.MIN_OBSERVATIONS
    drawdown = m.max_drawdown(values) if enough else None
    covariance_var = m.covariance(port_returns, port_returns) if enough else None

    def amount(pct: Decimal | None) -> Decimal | None:
        return portfolio_service.qm(covered_value * pct / HUNDRED) if pct is not None else None

    def stress(window_days: int) -> StressWindowOut | None:
        w = m.worst_window(values, window_days) if enough else None
        if w is None:
            return None
        return StressWindowOut(
            days=window_days,
            pct=w.pct.quantize(PCT),
            start=w.start,
            end=w.end,
            amount=portfolio_service.qm(covered_value * w.pct / HUNDRED),
        )

    asset_out: list[AssetRiskOut] = []
    for a in data.assets:
        rets = m.simple_returns(list(a.closes.values())) if a.closes else []
        beta_btc = None
        if a.closes and data.btc and not a.stablecoin:
            beta_btc = (
                Decimal(1)
                if a.crypto.source_id == "bitcoin"
                else m.beta(*_paired_returns(a.closes, data.btc))
            )
        contribution = None
        if a.stablecoin and covariance_var:
            contribution = ZERO
        elif a.closes and covariance_var and a.crypto.source_id in aligned:
            cov = m.covariance(asset_returns[a.crypto.source_id], port_returns)
            weight = a.position.market_value / covered_value if covered_value else ZERO
            contribution = weight * cov / covariance_var * HUNDRED if cov is not None else None
        adv = m.mean(a.volumes) if a.volumes else None
        to_volume = a.value_usd / adv * HUNDRED if adv else None
        own_dd = (
            m.max_drawdown(list(a.closes.items()))
            if a.closes and len(rets) >= m.MIN_OBSERVATIONS
            else None
        )
        asset_out.append(
            AssetRiskOut(
                asset=a.position.asset,
                weight_pct=a.position.weight_pct,
                market_value=a.position.market_value,
                is_stablecoin=a.stablecoin,
                covered=a.stablecoin or a.closes is not None,
                observations=len(rets),
                volatility_pct=_q(m.annualized_volatility_pct(rets)) if not a.stablecoin else ZERO,
                max_drawdown_pct=_q(own_dd.pct) if own_dd else None,
                beta_btc=_q(beta_btc, RATIO),
                var95_pct=_q(_times100(m.historical_var(rets, VAR_LEVELS[0])))
                if not a.stablecoin
                else ZERO,
                risk_contribution_pct=_q(contribution),
                avg_daily_volume_usd=portfolio_service.qm(adv) if adv is not None else None,
                position_to_volume_pct=_q(to_volume, Decimal("0.0001")),
                liquidity="high" if a.stablecoin else _liquidity(to_volume),
            )
        )

    weights = [a.position.weight_pct / HUNDRED for a in data.assets]
    hhi = m.hhi(weights)
    ordered = sorted((a.position.weight_pct for a in data.assets), reverse=True)
    stable_pct = sum((a.position.weight_pct for a in data.assets if a.stablecoin), ZERO)
    concentration = ConcentrationOut(
        hhi=hhi.quantize(Decimal("0.0001")),
        effective_assets=(Decimal(1) / hhi).quantize(RATIO) if hhi > 0 else ZERO,
        top1_pct=ordered[0] if ordered else ZERO,
        top3_pct=sum(ordered[:3], ZERO),
        stablecoin_pct=stable_pct,
    )

    top = sorted(moving, key=lambda a: a.position.market_value, reverse=True)[:CORRELATION_TOP]
    matrix: list[list[Decimal | None]] = []
    for a in top:
        row: list[Decimal | None] = []
        for b in top:
            if a is b:
                row.append(Decimal(1))
            else:
                row.append(
                    _q(m.correlation(*_paired_returns(a.closes or {}, b.closes or {})), RATIO)
                )
        matrix.append(row)

    port_beta = (
        m.beta(port_returns, m.simple_returns([data.btc[d] for d in days]))
        if enough and data.btc and all(d in data.btc for d in days)
        else None
    )
    volatility = m.annualized_volatility_pct(port_returns)
    var_out = [
        VarOut(
            confidence_pct=(level * 100).quantize(Decimal(1)),
            pct=_q(_times100(m.historical_var(port_returns, level))),
            amount=amount(_times100(m.historical_var(port_returns, level))),
        )
        for level in VAR_LEVELS
    ]
    es = _times100(m.expected_shortfall(port_returns, VAR_LEVELS[0]))
    worst_day = stress(1)

    result = RiskOut(
        currency=currency,
        window_days=window,
        period_start=days[0] if days and enough else None,
        period_end=days[-1] if days and enough else None,
        observations=len(port_returns),
        market_value=total,
        covered_value=portfolio_service.qm(covered_value),
        coverage_pct=(covered_value / total * HUNDRED).quantize(PCT) if total > 0 else ZERO,
        uncovered_assets=[a.position.asset.symbol for a in uncovered],
        volatility_pct=_q(volatility),
        drawdown=DrawdownOut(
            pct=_q(drawdown.pct) if drawdown else None,
            peak=drawdown.peak if drawdown else None,
            trough=drawdown.trough if drawdown else None,
            current_pct=_q(drawdown.current_pct) if drawdown else None,
        ),
        var=var_out,
        expected_shortfall_95=VarOut(confidence_pct=Decimal(95), pct=_q(es), amount=amount(es)),
        beta_btc=_q(port_beta, RATIO),
        worst_day=worst_day,
        stress=[s for s in (stress(d) for d in STRESS_DAYS) if s is not None],
        concentration=concentration,
        assets=asset_out,
        correlation=CorrelationOut(symbols=[a.position.asset.symbol for a in top], values=matrix),
        flags=[],
        data_source=DATA_SOURCE,
        methodology=METHODOLOGY,
        as_of=data.fetched_at or now,
    )
    result.flags = _flags(result)
    return result


def _times100(value: Decimal | None) -> Decimal | None:
    return value * HUNDRED if value is not None else None


def _flags(r: RiskOut) -> list[RiskFlagOut]:
    flags: list[RiskFlagOut] = []
    if r.volatility_pct is not None and r.volatility_pct >= 50:
        flags.append(
            RiskFlagOut(
                id="high_volatility",
                severity="risk" if r.volatility_pct >= 80 else "attention",
                title="Volatilidade elevada",
                message=f"A carteira atual teria oscilado {_pct_text(r.volatility_pct)} ao ano "
                f"nos últimos {r.window_days} dias.",
                basis="Desvio-padrão dos retornos diários × √365. Atenção a partir de 50%; "
                "risco a partir de 80%.",
            )
        )
    if r.drawdown.current_pct is not None and r.drawdown.current_pct <= -20:
        flags.append(
            RiskFlagOut(
                id="in_drawdown",
                severity="attention",
                title="Carteira abaixo do pico",
                message=f"Com as quantidades atuais, o valor está "
                f"{_pct_text(-r.drawdown.current_pct)} abaixo do maior valor do período.",
                basis="Último valor ÷ maior valor anterior da série simulada − 1. "
                "Destacado a partir de −20%.",
            )
        )
    if (
        r.concentration.effective_assets
        and r.concentration.effective_assets < 3
        and len(r.assets) > 1
    ):
        eff = f"{r.concentration.effective_assets:.1f}".replace(".", ",")
        flags.append(
            RiskFlagOut(
                id="low_diversification",
                severity="attention",
                title="Diversificação efetiva baixa",
                message=f"Pelos pesos atuais, a carteira equivale a {eff} ativos de mesmo peso.",
                basis="1 ÷ índice Herfindahl-Hirschman (soma dos pesos ao quadrado). "
                "Destacado abaixo de 3.",
            )
        )
    illiquid = [a for a in r.assets if a.liquidity in ("medium", "low")]
    if illiquid:
        worst = max(illiquid, key=lambda a: a.position_to_volume_pct or ZERO)
        flags.append(
            RiskFlagOut(
                id="liquidity",
                severity="risk" if worst.liquidity == "low" else "attention",
                title="Liquidez limitada",
                message=f"Sua posição em {worst.asset.symbol} equivale a "
                f"{_pct_text(worst.position_to_volume_pct or ZERO, 1)} do volume médio diário "
                "negociado; vendê-la de uma vez pode mover o preço.",
                basis="Valor da posição ÷ volume médio diário de 30 dias no par USDT da "
                "Binance. Atenção acima de 1%; risco acima de 10%.",
            )
        )
    symbols = r.correlation.symbols
    weights = {a.asset.symbol: a.weight_pct for a in r.assets}
    pairs = [
        (symbols[i], symbols[j], rho)
        for i, row in enumerate(r.correlation.values)
        for j, rho in enumerate(row)
        if j > i
        and rho is not None
        and rho >= Decimal("0.8")
        and weights.get(symbols[i], ZERO) >= 10
        and weights.get(symbols[j], ZERO) >= 10
    ]
    if pairs:
        a, b, rho = max(pairs, key=lambda p: p[2])
        flags.append(
            RiskFlagOut(
                id="correlation",
                severity="attention",
                title="Ativos relevantes muito correlacionados",
                message=f"{a} e {b} tiveram correlação de {str(rho).replace('.', ',')} nos "
                "retornos diários do período: tendem a cair juntos.",
                basis="Correlação de Pearson dos retornos diários, entre ativos com peso de "
                "pelo menos 10%. Destacado a partir de 0,80.",
            )
        )
    if r.uncovered_assets:
        flags.append(
            RiskFlagOut(
                id="coverage",
                severity="info",
                title="Ativos sem histórico de preços",
                message=f"{', '.join(r.uncovered_assets)} não têm candles diários disponíveis e "
                f"ficaram fora das métricas "
                f"({_pct_text(HUNDRED - r.coverage_pct, 1)} da carteira).",
                basis="Ativos sem par USDT na Binance ou com mercado de referência divergente.",
            )
        )
    if r.concentration.stablecoin_pct >= 1:
        flags.append(
            RiskFlagOut(
                id="stablecoins",
                severity="info",
                title="Risco de emissor em stablecoins",
                message=f"{_pct_text(r.concentration.stablecoin_pct)} da carteira está em "
                "stablecoins, tratadas como US$ 1 constante.",
                basis="Ativos atrelados ao dólar por símbolo ou comportamento. O risco de "
                "perda da paridade não está nas métricas.",
            )
        )
    return flags


async def scenario(
    db: AsyncSession,
    portfolio: Portfolio,
    currency: Currency,
    body: ScenarioIn,
    provider: CandleProvider,
) -> ScenarioOut:
    data = await _collect(db, portfolio, currency, body.window, provider)
    overrides = {str(o.asset_id): o.change_pct for o in body.overrides}
    exposures = []
    for a in data.assets:
        beta_btc = None
        if a.closes and data.btc and a.crypto.source_id != "bitcoin":
            beta_btc = m.beta(*_paired_returns(a.closes, data.btc))
        exposures.append(
            Exposure(
                key=str(a.position.asset.id),
                value=a.position.market_value,
                beta_btc=beta_btc,
                is_btc=a.crypto.source_id == "bitcoin",
                is_stablecoin=a.stablecoin,
            )
        )
    lines = simulate(exposures, body.btc_change_pct, overrides)
    by_id = {str(a.position.asset.id): a.position.asset for a in data.assets}
    before = sum((ln.value for ln in lines), ZERO)
    after = sum((ln.new_value for ln in lines), ZERO)
    notes = [
        "Simulação mecânica sobre as posições de hoje: não é previsão nem recomendação.",
        f"A variação do Bitcoin é propagada pelo beta de cada ativo ao Bitcoin nos últimos "
        f"{body.window} dias; stablecoins ficam estáveis.",
    ]
    if any(ln.method == "assumed_beta_1" for ln in lines):
        notes.append("Ativos sem histórico suficiente receberam a mesma variação do Bitcoin.")
    ignored = set(overrides) - set(by_id)
    if ignored:
        notes.append("Ajustes para ativos fora da carteira foram ignorados.")
    return ScenarioOut(
        currency=currency,
        btc_change_pct=body.btc_change_pct,
        market_value=portfolio_service.qm(before),
        new_value=portfolio_service.qm(after),
        pnl=portfolio_service.qm(after - before),
        pnl_pct=((after / before - 1) * HUNDRED).quantize(PCT) if before > 0 else None,
        lines=[
            ScenarioLineOut(
                asset=by_id[ln.key],
                market_value=portfolio_service.qm(ln.value),
                change_pct=ln.change_pct.quantize(PCT),
                method=ln.method,
                new_value=portfolio_service.qm(ln.new_value),
                pnl=portfolio_service.qm(ln.pnl),
            )
            for ln in lines
        ],
        notes=notes,
        as_of=data.fetched_at or utcnow(),
    )
