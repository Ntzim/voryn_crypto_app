"""Position engine: replays a portfolio's transactions into positions and cash flows.

Pure and deterministic (no I/O, Decimal only), so every figure shown to users can be
reproduced and unit-tested against hand-computed examples.

Accounting rules (weighted average cost):

- buy / deposit: +qty (− fee withheld in the asset); cost + gross + fee;
  flow + (gross + fee).
- sell: −qty; cost − avg × qty; flow − (gross − fee);
  realized (gross − fee) − avg × qty.
- withdrawal: −qty; cost − avg × qty; flow − gross (avg × qty when no price).
- transfer: − network fee units only; their cost basis is realized as a loss.
- fee: −qty; cost basis realized as a loss.
- conversion A→B: A is disposed (realized proceeds − avg_A × qty), B acquired at
  proceeds; no external flow.

"External flows" are money entering (+) or leaving (−) the tracked portfolio; they drive
time-weighted and money-weighted returns. Internal transfers and conversions move value
inside the portfolio, so they never count as contributions or profit. Fees paid in units
of an asset are an expense: their cost basis is realized as a loss.

All monetary values are in one *reporting currency*, converted by the caller with the
FX rate stored on each transaction.
"""

import enum
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, localcontext

ZERO = Decimal(0)
_PRECISION = 40


class TxType(enum.StrEnum):
    BUY = "buy"
    SELL = "sell"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRANSFER = "transfer"
    FEE = "fee"
    CONVERSION = "conversion"


#: Types that require a unit price (they define value, not just movement).
PRICED_TYPES = frozenset({TxType.BUY, TxType.SELL, TxType.DEPOSIT, TxType.CONVERSION})


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    id: str
    type: TxType
    executed_at: datetime
    asset: uuid.UUID
    quantity: Decimal
    #: quantity × unit price, in the reporting currency (None when no price was given).
    gross: Decimal | None = None
    #: fee charged in the quote currency, converted to the reporting currency.
    fee: Decimal = ZERO
    #: fee charged in units of `asset` (network/withdrawal fees).
    fee_quantity: Decimal = ZERO
    to_asset: uuid.UUID | None = None
    to_quantity: Decimal | None = None


@dataclass(slots=True)
class Position:
    asset: uuid.UUID
    quantity: Decimal = ZERO
    cost_basis: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    fees: Decimal = ZERO
    #: total cost of every acquisition (buys, deposits, conversions in).
    total_acquired_cost: Decimal = ZERO

    @property
    def average_cost(self) -> Decimal | None:
        return self.cost_basis / self.quantity if self.quantity > 0 else None


@dataclass(frozen=True, slots=True)
class ExternalFlow:
    at: datetime
    amount: Decimal  # + money in, − money out
    entry_id: str


class InsufficientBalanceError(Exception):
    def __init__(self, entry_id: str, asset: uuid.UUID, available: Decimal, requested: Decimal):
        self.entry_id = entry_id
        self.asset = asset
        self.available = available
        self.requested = requested
        super().__init__(
            f"entry {entry_id}: needs {requested} of {asset}, only {available} available"
        )


class InvalidEntryError(Exception):
    def __init__(self, entry_id: str, reason: str):
        self.entry_id = entry_id
        self.reason = reason
        super().__init__(f"entry {entry_id}: {reason}")


@dataclass(slots=True)
class Ledger:
    positions: dict[uuid.UUID, Position] = field(default_factory=dict)
    flows: list[ExternalFlow] = field(default_factory=list)
    #: last known unit price per asset (reporting currency), a fallback for valuation.
    last_price: dict[uuid.UUID, Decimal] = field(default_factory=dict)

    def position(self, asset: uuid.UUID) -> Position:
        if asset not in self.positions:
            self.positions[asset] = Position(asset=asset)
        return self.positions[asset]

    def _acquire(self, asset: uuid.UUID, quantity: Decimal, cost: Decimal) -> None:
        pos = self.position(asset)
        pos.quantity += quantity
        pos.cost_basis += cost
        pos.total_acquired_cost += cost

    def _dispose(self, entry: LedgerEntry, asset: uuid.UUID, quantity: Decimal) -> Decimal:
        """Remove units at average cost; returns the cost basis removed."""
        pos = self.position(asset)
        if quantity > pos.quantity:
            raise InsufficientBalanceError(entry.id, asset, pos.quantity, quantity)
        if quantity == pos.quantity:
            removed = pos.cost_basis
            pos.quantity, pos.cost_basis = ZERO, ZERO
        else:
            removed = pos.cost_basis * quantity / pos.quantity
            pos.quantity -= quantity
            pos.cost_basis -= removed
        return removed

    def _expense_units(self, entry: LedgerEntry, quantity: Decimal) -> None:
        if quantity <= 0:
            return
        removed = self._dispose(entry, entry.asset, quantity)
        pos = self.position(entry.asset)
        pos.realized_pnl -= removed
        pos.fees += removed

    def apply(self, entry: LedgerEntry) -> Decimal:
        """Apply one entry; returns its external flow (0 for internal movements)."""
        with localcontext() as ctx:
            ctx.prec = _PRECISION
            flow = self._apply(entry)
        if flow:
            self.flows.append(ExternalFlow(entry.executed_at, flow, entry.id))
        return flow

    def _apply(self, e: LedgerEntry) -> Decimal:
        if e.quantity <= 0:
            raise InvalidEntryError(e.id, "quantity must be positive")
        if e.type in PRICED_TYPES and e.gross is None:
            raise InvalidEntryError(e.id, f"{e.type} requires a unit price")
        if e.gross is not None and e.gross > 0:
            self.last_price[e.asset] = e.gross / e.quantity

        match e.type:
            case TxType.BUY | TxType.DEPOSIT:
                assert e.gross is not None
                # A fee withheld in the received asset (e.g. Binance) shrinks the units
                # received; the full cost stays in their basis.
                if e.fee_quantity >= e.quantity:
                    raise InvalidEntryError(e.id, "fee exceeds the received quantity")
                cost = e.gross + e.fee
                self._acquire(e.asset, e.quantity - e.fee_quantity, cost)
                self.position(e.asset).fees += e.fee + e.gross * e.fee_quantity / e.quantity
                return cost
            case TxType.SELL:
                assert e.gross is not None
                removed = self._dispose(e, e.asset, e.quantity)
                proceeds = e.gross - e.fee
                pos = self.position(e.asset)
                pos.realized_pnl += proceeds - removed
                pos.fees += e.fee
                return -proceeds
            case TxType.WITHDRAWAL:
                removed = self._dispose(e, e.asset, e.quantity)
                self._expense_units(e, e.fee_quantity)
                if e.fee:
                    pos = self.position(e.asset)
                    pos.realized_pnl -= e.fee
                    pos.fees += e.fee
                return -(e.gross if e.gross is not None else removed)
            case TxType.TRANSFER:
                # Moving between own wallets/exchanges: holdings change only by the fee.
                if e.quantity < e.fee_quantity:
                    raise InvalidEntryError(e.id, "fee exceeds the transferred quantity")
                if e.quantity > self.position(e.asset).quantity:
                    raise InsufficientBalanceError(
                        e.id, e.asset, self.position(e.asset).quantity, e.quantity
                    )
                self._expense_units(e, e.fee_quantity)
                return ZERO
            case TxType.FEE:
                self._expense_units(e, e.quantity)
                return ZERO
            case TxType.CONVERSION:
                assert e.gross is not None
                if e.to_asset is None or not e.to_quantity or e.to_quantity <= 0:
                    raise InvalidEntryError(e.id, "conversion requires a target asset and quantity")
                if e.to_asset == e.asset:
                    raise InvalidEntryError(e.id, "conversion must change asset")
                removed = self._dispose(e, e.asset, e.quantity)
                proceeds = e.gross - e.fee
                pos = self.position(e.asset)
                pos.realized_pnl += proceeds - removed
                pos.fees += e.fee
                self._acquire(e.to_asset, e.to_quantity, proceeds)
                if e.to_quantity > 0 and proceeds > 0:
                    self.last_price[e.to_asset] = proceeds / e.to_quantity
                return ZERO
        raise InvalidEntryError(e.id, f"unsupported type {e.type}")  # pragma: no cover

    def quantities(self) -> dict[uuid.UUID, Decimal]:
        return {a: p.quantity for a, p in self.positions.items() if p.quantity > 0}


def replay(entries: Iterable[LedgerEntry]) -> Ledger:
    """Replay entries in chronological order (callers sort by executed_at, created_at)."""
    ledger = Ledger()
    for entry in entries:
        ledger.apply(entry)
    return ledger
