"""Position engine against hand-computed examples."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from app.modules.portfolio.engine import (
    InsufficientBalanceError,
    InvalidEntryError,
    LedgerEntry,
    TxType,
    replay,
)

BTC, ETH, USDT = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
T0 = datetime(2026, 1, 1, tzinfo=UTC)
_counter = iter(range(1000))


def e(
    type_: TxType, asset: uuid.UUID, qty: str, gross: str | None = None, **kw: object
) -> LedgerEntry:
    n = next(_counter)
    return LedgerEntry(
        id=f"t{n}",
        type=type_,
        executed_at=T0 + timedelta(days=n),
        asset=asset,
        quantity=D(qty),
        gross=D(gross) if gross is not None else None,
        **kw,  # type: ignore[arg-type]
    )


def test_weighted_average_cost_and_realized_pnl() -> None:
    ledger = replay(
        [
            e(TxType.BUY, BTC, "1", "100000", fee=D("100")),  # cost 100,100
            e(TxType.BUY, BTC, "1", "120000"),  # cost 120,000 → avg 110,050
            e(TxType.SELL, BTC, "0.5", "75000", fee=D("75")),  # proceeds 74,925
        ]
    )
    btc = ledger.positions[BTC]
    assert btc.quantity == D("1.5")
    assert btc.average_cost == D("110050")
    assert btc.cost_basis == D("165075")
    # 74,925 − 0.5 × 110,050 = 19,900
    assert btc.realized_pnl == D("19900")
    assert btc.fees == D("175")
    assert [f.amount for f in ledger.flows] == [D("100100"), D("120000"), D("-74925")]


def test_selling_everything_clears_cost_basis() -> None:
    ledger = replay([e(TxType.BUY, ETH, "3", "9000"), e(TxType.SELL, ETH, "3", "6000")])
    eth = ledger.positions[ETH]
    assert eth.quantity == 0 and eth.cost_basis == 0
    assert eth.realized_pnl == D("-3000")
    assert eth.average_cost is None


def test_cannot_sell_more_than_held() -> None:
    with pytest.raises(InsufficientBalanceError) as info:
        replay([e(TxType.BUY, BTC, "1", "100"), e(TxType.SELL, BTC, "1.0001", "100")])
    assert info.value.available == D("1")


def test_transfer_is_neither_contribution_nor_profit() -> None:
    ledger = replay(
        [
            e(TxType.BUY, BTC, "1", "100000"),
            # Exchange → own wallet, 0.0005 BTC network fee.
            e(TxType.TRANSFER, BTC, "1", fee_quantity=D("0.0005")),
        ]
    )
    btc = ledger.positions[BTC]
    assert btc.quantity == D("0.9995")
    assert len(ledger.flows) == 1  # only the purchase
    # The fee's cost basis (0.0005 × 100,000 = 50) is an expense.
    assert btc.realized_pnl == D("-50")
    assert btc.cost_basis == D("99950")
    assert btc.average_cost == D("100000")


def test_buy_with_fee_withheld_in_asset_keeps_full_cost_in_basis() -> None:
    ledger = replay([e(TxType.BUY, BTC, "1", "100000", fee_quantity=D("0.001"))])
    btc = ledger.positions[BTC]
    assert btc.quantity == D("0.999")
    assert btc.cost_basis == D("100000")
    assert btc.realized_pnl == 0
    assert btc.fees == D("100")


def test_conversion_realizes_source_and_sets_target_basis() -> None:
    ledger = replay(
        [
            e(TxType.BUY, USDT, "1000", "1000"),
            e(TxType.BUY, USDT, "1000", "1100"),  # avg 1.05
            # 1,000 USDT (worth 1,000) → 0.01 BTC, 2 fee
            e(
                TxType.CONVERSION,
                USDT,
                "1000",
                "1000",
                fee=D("2"),
                to_asset=BTC,
                to_quantity=D("0.01"),
            ),
        ]
    )
    usdt, btc = ledger.positions[USDT], ledger.positions[BTC]
    assert usdt.quantity == D("1000")
    assert usdt.realized_pnl == D("-52")  # 998 − 1,050
    assert btc.quantity == D("0.01")
    assert btc.cost_basis == D("998")
    assert len(ledger.flows) == 2  # conversions are internal


def test_deposit_and_withdrawal_are_external_flows_without_realization() -> None:
    ledger = replay(
        [
            e(TxType.DEPOSIT, ETH, "2", "6000"),
            e(TxType.WITHDRAWAL, ETH, "1", "4000"),
            e(TxType.WITHDRAWAL, ETH, "0.5"),  # no price given: valued at average cost
        ]
    )
    eth = ledger.positions[ETH]
    assert eth.quantity == D("0.5")
    assert eth.realized_pnl == 0
    assert [f.amount for f in ledger.flows] == [D("6000"), D("-4000"), D("-1500")]


def test_fee_type_is_an_expense() -> None:
    ledger = replay([e(TxType.BUY, ETH, "1", "3000"), e(TxType.FEE, ETH, "0.01")])
    eth = ledger.positions[ETH]
    assert eth.quantity == D("0.99")
    assert eth.realized_pnl == D("-30")


@pytest.mark.parametrize(
    "entry",
    [
        e(TxType.BUY, BTC, "1"),  # missing price
        e(TxType.BUY, BTC, "0", "1"),  # non-positive quantity
        e(TxType.CONVERSION, BTC, "1", "1", to_asset=BTC, to_quantity=D("1")),
    ],
)
def test_invalid_entries_are_rejected(entry: LedgerEntry) -> None:
    with pytest.raises((InvalidEntryError, InsufficientBalanceError)):
        replay([entry])


def test_average_cost_is_exact_with_repeating_decimals() -> None:
    ledger = replay(
        [
            e(TxType.BUY, BTC, "3", "100"),
            e(TxType.SELL, BTC, "1", "50"),
            e(TxType.SELL, BTC, "1", "50"),
            e(TxType.SELL, BTC, "1", "50"),
        ]
    )
    btc = ledger.positions[BTC]
    assert btc.quantity == 0 and btc.cost_basis == 0
    assert btc.realized_pnl.quantize(D("0.00000001")) == D("50.00000000")
