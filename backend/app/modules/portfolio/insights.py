"""Deterministic portfolio insights.

Every insight is a rule over computed figures, with its threshold and method stated in
`basis`, so users can verify it. No generated text, no prediction.
"""

import itertools
import math
from datetime import date, timedelta
from decimal import Decimal

from app.modules.portfolio.schemas import InsightOut, PositionOut, SummaryOut

#: Heuristic list of USD-pegged stablecoins (by symbol) for exposure insights.
STABLECOINS = frozenset(
    {
        "USDT",
        "USDC",
        "DAI",
        "FDUSD",
        "TUSD",
        "USDE",
        "PYUSD",
        "USDS",
        "BUSD",
        "USD1",
        "USDD",
        "GUSD",
    }
)
CONCENTRATION_ATTENTION = Decimal(50)
CONCENTRATION_RISK = Decimal(80)
DRAWDOWN_THRESHOLD = Decimal(-20)
MOVE_THRESHOLD = Decimal(5)
CORRELATION_THRESHOLD = 0.8
MIN_CORRELATION_OBSERVATIONS = 30


def _pct(value: Decimal, digits: int = 0) -> str:
    return f"{value:.{digits}f}".replace(".", ",") + "%"


def aligned_returns(closes: dict[str, dict[date, Decimal]]) -> dict[str, list[Decimal]]:
    """Daily simple returns over the days where every series has consecutive closes."""
    if not closes:
        return {}
    common = sorted(set.intersection(*(set(c) for c in closes.values())))
    result: dict[str, list[Decimal]] = {name: [] for name in closes}
    for prev, day in itertools.pairwise(common):
        if day - prev != timedelta(days=1):
            continue
        for name, series in closes.items():
            if series[prev] > 0:
                result[name].append(series[day] / series[prev] - 1)
    return result


def pearson(xs: list[Decimal], ys: list[Decimal]) -> float | None:
    n = min(len(xs), len(ys))
    if n < MIN_CORRELATION_OBSERVATIONS:
        return None
    x, y = [float(v) for v in xs[:n]], [float(v) for v in ys[:n]]
    mx, my = sum(x) / n, sum(y) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    vx = sum((a - mx) ** 2 for a in x)
    vy = sum((b - my) ** 2 for b in y)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


def build(summary: SummaryOut, returns: dict[str, list[Decimal]]) -> list[InsightOut]:
    positions: list[PositionOut] = summary.positions
    if not positions:
        return []
    items: list[InsightOut] = []

    top = positions[0]
    if top.weight_pct >= CONCENTRATION_ATTENTION:
        single = len(positions) == 1
        items.append(
            InsightOut(
                id="concentration",
                severity="risk" if top.weight_pct >= CONCENTRATION_RISK else "attention",
                title="Exposição concentrada",
                message=(
                    f"{top.asset.name} representa {_pct(top.weight_pct)} da sua carteira. "
                    + (
                        "Todo o patrimônio está em um único ativo."
                        if single
                        else "Sua exposição está concentrada em um único ativo."
                    )
                ),
                basis="Valor de mercado do ativo ÷ valor total da carteira, a preços atuais. "
                "Alerta a partir de 50%; risco a partir de 80%.",
            )
        )

    stable = sum((p.weight_pct for p in positions if p.asset.symbol in STABLECOINS), Decimal(0))
    if stable >= 1:
        items.append(
            InsightOut(
                id="stablecoins",
                severity="info",
                title="Reserva em stablecoins",
                message=f"Stablecoins representam {_pct(stable)} da carteira — parcela com "
                "menor volatilidade em dólar, mas sujeita a risco do emissor.",
                basis="Soma do peso de ativos atrelados ao dólar (USDT, USDC, DAI e similares).",
            )
        )

    movers = [
        p
        for p in positions
        if p.change_pct_24h is not None and abs(p.change_pct_24h) >= MOVE_THRESHOLD
    ]
    if movers:
        mover = max(movers, key=lambda p: abs(p.change_pct_24h or Decimal(0)))
        change = mover.change_pct_24h or Decimal(0)
        direction = "alta" if change > 0 else "queda"
        items.append(
            InsightOut(
                id="mover_24h",
                severity="info" if change > 0 else "attention",
                title=f"Movimento relevante em {mover.asset.symbol}",
                message=f"{mover.asset.name} registra {direction} de {_pct(abs(change), 1)} nas "
                f"últimas 24 horas e pesa {_pct(mover.weight_pct)} na sua carteira.",
                basis="Variação de preço em 24h informada pelo provedor de dados (base USD). "
                "Destacado a partir de 5%.",
            )
        )

    losers = [
        p
        for p in positions
        if p.unrealized_pct is not None and p.unrealized_pct <= DRAWDOWN_THRESHOLD
    ]
    if losers:
        names = ", ".join(p.asset.symbol for p in losers[:4])
        items.append(
            InsightOut(
                id="underwater_positions",
                severity="attention",
                title="Posições abaixo do preço médio",
                message=f"{len(losers)} posição(ões) acumulam queda superior a 20% sobre o preço "
                f"médio de compra: {names}.",
                basis="(Valor de mercado − custo de aquisição) ÷ custo de aquisição, por ativo.",
            )
        )

    if len(positions) >= 2 and len(returns) == 2:
        a, b = positions[0].asset, positions[1].asset
        rho = pearson(returns.get(a.symbol, []), returns.get(b.symbol, []))
        if rho is not None and rho >= CORRELATION_THRESHOLD:
            rho_text = f"{rho:.2f}".replace(".", ",")
            items.append(
                InsightOut(
                    id="correlation",
                    severity="attention",
                    title="Ativos que se movem juntos",
                    message=f"{a.symbol} e {b.symbol}, seus dois maiores ativos, tiveram "
                    f"correlação de {rho_text} nos retornos diários recentes — tendem a subir e "
                    "cair juntos, o que reduz o efeito da diversificação.",
                    basis="Correlação de Pearson dos retornos diários de fechamento (UTC) dos "
                    "últimos 90 dias. Destacado a partir de 0,80.",
                )
            )
    return items
