"""Exchange records → portfolio transactions.

* Trade against BRL → buy/sell in BRL at the executed price.
* Trade against a dollar stablecoin → conversion between the two assets, valued in USD
  (1 stablecoin = US$ 1).
* Commission → a separate `fee` transaction in the asset charged, 1 µs after the trade.
* Crypto deposit → deposit valued at the asset's daily close (Binance, UTC) of that day.
* Withdrawal → withdrawal, plus a `fee` transaction for the network fee.

A record that cannot be mapped without guessing (unknown asset, no historical price)
raises NeedsReviewError with the reason; it is never imported with invented values.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.modules.exchange_connections.models import ExchangeRecord
from app.modules.market_data.models import Cryptocurrency
from app.modules.portfolio.engine import TxType
from app.modules.portfolio.insights import STABLECOINS
from app.modules.portfolio.schemas import TransactionIn

USD_STABLES = frozenset({"USDT", "USDC", "FDUSD"})
FEE_OFFSET = timedelta(microseconds=1)


class NeedsReviewError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Resolver:
    asset: Callable[[str], Awaitable[Cryptocurrency | None]]
    #: USD daily close of an asset on a UTC day, or None
    usd_close: Callable[[Cryptocurrency, date], Awaitable[Decimal | None]]


Mapped = list[tuple[TransactionIn, str]]


async def _asset(resolver: Resolver, symbol: str) -> Cryptocurrency:
    crypto = await resolver.asset(symbol)
    if crypto is None:
        raise NeedsReviewError(f"O ativo {symbol} não existe no catálogo da Voryn.")
    return crypto


def _dec(value: object) -> Decimal:
    return Decimal(str(value))


async def to_transactions(record: ExchangeRecord, exchange_id: str, resolver: Resolver) -> Mapped:
    d, at, ext = record.data, record.occurred_at, record.external_id
    out: Mapped = []

    async def fee(symbol: str, quantity: Decimal) -> None:
        if quantity <= 0:
            return
        crypto = await _asset(resolver, symbol)
        out.append(
            (
                TransactionIn(
                    type=TxType.FEE,
                    asset_id=crypto.id,
                    quantity=quantity,
                    executed_at=at + FEE_OFFSET,
                    exchange_id=exchange_id,
                    notes=f"Taxa · {ext}",
                ),
                f"{ext}:fee",
            )
        )

    if record.kind == "trade":
        base = await _asset(resolver, d["base"])
        qty, price, quote_qty = _dec(d["qty"]), _dec(d["price"]), _dec(d["quote_qty"])
        commission, commission_asset = _dec(d["commission"]), str(d["commission_asset"])
        note = f"{d['symbol']} · {ext}"
        if d["quote"] == "BRL":
            out.append(
                (
                    TransactionIn(
                        type=TxType.BUY if d["side"] == "buy" else TxType.SELL,
                        asset_id=base.id,
                        quantity=qty,
                        unit_price=price,
                        quote_currency="BRL",
                        fee_amount=commission if commission_asset == "BRL" else Decimal(0),
                        executed_at=at,
                        exchange_id=exchange_id,
                        notes=note,
                    ),
                    ext,
                )
            )
            if commission_asset != "BRL":
                await fee(commission_asset, commission)
        elif d["quote"] in USD_STABLES:
            quote = await _asset(resolver, d["quote"])
            buying = d["side"] == "buy"
            out.append(
                (
                    TransactionIn(
                        type=TxType.CONVERSION,
                        asset_id=quote.id if buying else base.id,
                        quantity=quote_qty if buying else qty,
                        unit_price=Decimal(1) if buying else price,
                        quote_currency="USD",
                        to_asset_id=base.id if buying else quote.id,
                        to_quantity=qty if buying else quote_qty,
                        executed_at=at,
                        exchange_id=exchange_id,
                        notes=note,
                    ),
                    ext,
                )
            )
            await fee(commission_asset, commission)
        else:
            raise NeedsReviewError(f"Mercado {d['symbol']} não suportado.")
        return out

    coin = await _asset(resolver, d["coin"])
    amount = _dec(d["amount"])
    if record.kind == "deposit":
        if d["coin"] in STABLECOINS:
            value: Decimal | None = Decimal(1)
            source = "paridade com o dólar"
        else:
            value = await resolver.usd_close(coin, at.date())
            source = f"fechamento diário Binance de {at:%d/%m/%Y} (UTC)"
        if value is None:
            raise NeedsReviewError(
                f"Sem preço histórico de {d['coin']} em {at:%d/%m/%Y} para valorizar o depósito."
            )
        out.append(
            (
                TransactionIn(
                    type=TxType.DEPOSIT,
                    asset_id=coin.id,
                    quantity=amount,
                    unit_price=value,
                    quote_currency="USD",
                    executed_at=at,
                    exchange_id=exchange_id,
                    notes=f"Depósito · preço: {source} · {ext}",
                ),
                ext,
            )
        )
        return out

    if record.kind == "withdrawal":
        out.append(
            (
                TransactionIn(
                    type=TxType.WITHDRAWAL,
                    asset_id=coin.id,
                    quantity=amount,
                    executed_at=at,
                    exchange_id=exchange_id,
                    notes=f"Saque · {ext}",
                ),
                ext,
            )
        )
        await fee(d["coin"], _dec(d.get("fee") or 0))
        return out

    raise NeedsReviewError(f"Tipo de registro não suportado: {record.kind}.")


def describe(record: ExchangeRecord) -> str:
    d = record.data
    if record.kind == "trade":
        side = "Compra" if d["side"] == "buy" else "Venda"
        return f"{side} de {d['qty']} {d['base']} a {d['price']} {d['quote']} ({d['symbol']})"
    if record.kind == "deposit":
        return f"Depósito de {d['amount']} {d['coin']}"
    if record.kind == "withdrawal":
        return f"Saque de {d['amount']} {d['coin']} (taxa {d.get('fee') or 0})"
    return record.kind
