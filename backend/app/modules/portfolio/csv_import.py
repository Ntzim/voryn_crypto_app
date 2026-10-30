"""CSV import (Voryn template).

- Delimiter `,` or `;` (auto-detected); headers in Portuguese or English.
- Numbers as `1234.56` or `1.234,56`; dates ISO 8601 or `dd/mm/aaaa [hh:mm[:ss]]`.
  Dates without offset are interpreted in the user's timezone.
- Rows are deduplicated by `id_externo` when given, else by a fingerprint of their content,
  so re-importing the same file never duplicates transactions.
"""

import csv
import hashlib
import io
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data import service as market
from app.modules.portfolio.engine import TxType
from app.modules.portfolio.models import Exchange, Transaction
from app.modules.portfolio.schemas import TransactionIn

MAX_ROWS = 5000
SOURCE = "csv"

COLUMNS = [
    "data",
    "tipo",
    "ativo",
    "quantidade",
    "preco_unitario",
    "moeda",
    "taxa",
    "taxa_no_ativo",
    "exchange",
    "exchange_destino",
    "ativo_destino",
    "quantidade_destino",
    "observacoes",
    "id_externo",
]
_ALIASES = {
    "date": "data",
    "type": "tipo",
    "asset": "ativo",
    "quantity": "quantidade",
    "unit_price": "preco_unitario",
    "price": "preco_unitario",
    "currency": "moeda",
    "fee": "taxa",
    "fee_quantity": "taxa_no_ativo",
    "to_exchange": "exchange_destino",
    "to_asset": "ativo_destino",
    "to_quantity": "quantidade_destino",
    "notes": "observacoes",
    "external_id": "id_externo",
}
_TYPES = {
    "compra": TxType.BUY,
    "buy": TxType.BUY,
    "venda": TxType.SELL,
    "sell": TxType.SELL,
    "deposito": TxType.DEPOSIT,
    "depósito": TxType.DEPOSIT,
    "deposit": TxType.DEPOSIT,
    "retirada": TxType.WITHDRAWAL,
    "saque": TxType.WITHDRAWAL,
    "withdrawal": TxType.WITHDRAWAL,
    "transferencia": TxType.TRANSFER,
    "transferência": TxType.TRANSFER,
    "transfer": TxType.TRANSFER,
    "taxa": TxType.FEE,
    "fee": TxType.FEE,
    "conversao": TxType.CONVERSION,
    "conversão": TxType.CONVERSION,
    "conversion": TxType.CONVERSION,
}
_BR_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$")

TEMPLATE = (
    ";".join(COLUMNS)
    + "\n2026-01-15 10:30;compra;BTC;0,01;350000,00;BRL;15,00;;mercado-bitcoin;;;;"
    + "Primeira compra;\n"
    + "16/01/2026 09:00;transferencia;BTC;0,01;;;;0,0001;mercado-bitcoin;carteira;;;"
    + "Para cold wallet;\n"
    + "2026-02-01T12:00:00-03:00;conversao;USDT;500;1,00;USD;0,50;;binance;;ETH;0,15;;binance-123\n"
)


@dataclass
class ParsedRow:
    line: int
    errors: list[str] = field(default_factory=list)
    data: TransactionIn | None = None
    external_id: str | None = None
    duplicate: bool = False
    raw: dict[str, str] = field(default_factory=dict)


def parse_decimal(value: str) -> Decimal | None:
    value = value.strip().replace(" ", "")
    if not value:
        return None
    if "," in value and "." in value:
        # The right-most separator is the decimal one.
        value = (
            value.replace(".", "").replace(",", ".")
            if value.rfind(",") > value.rfind(".")
            else value.replace(",", "")
        )
    elif "," in value:
        value = value.replace(",", ".")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"número inválido: {value}") from exc
    if not number.is_finite():
        raise ValueError(f"número inválido: {value}")
    return number


def parse_datetime(value: str, tz: ZoneInfo) -> datetime:
    value = value.strip()
    match = _BR_DATE.match(value)
    if match:
        d, m, y, hh, mm, ss = match.groups()
        parsed = datetime(int(y), int(m), int(d), int(hh or 0), int(mm or 0), int(ss or 0))
    else:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                f"data inválida: {value} (use AAAA-MM-DD HH:MM ou DD/MM/AAAA HH:MM)"
            ) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)


def _reader(content: str) -> csv.DictReader[str]:
    content = content.lstrip("﻿")
    first_line = content.split("\n", 1)[0]
    delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","
    return csv.DictReader(io.StringIO(content), delimiter=delimiter)


def _fingerprint(row: dict[str, str]) -> str:
    canonical = "|".join(row.get(c, "").strip().lower() for c in COLUMNS if c != "observacoes")
    return hashlib.sha256(canonical.encode()).hexdigest()[:40]


async def parse(
    db: AsyncSession, portfolio_id: uuid.UUID, content: str, timezone: str
) -> tuple[list[ParsedRow], list[str]]:
    """Parse and validate every row. Returns (rows, file-level errors)."""
    reader = _reader(content)
    headers = [
        _ALIASES.get(h.strip().lower(), h.strip().lower()) for h in (reader.fieldnames or [])
    ]
    missing = {"data", "tipo", "ativo", "quantidade"} - set(headers)
    if missing:
        return [], [f"Colunas obrigatórias ausentes: {', '.join(sorted(missing))}."]
    reader.fieldnames = headers

    tz = ZoneInfo(timezone)
    exchanges = set((await db.execute(select(Exchange.id))).scalars())
    existing = set(
        (
            await db.execute(
                select(Transaction.external_id).where(
                    Transaction.portfolio_id == portfolio_id, Transaction.source == SOURCE
                )
            )
        ).scalars()
    )
    asset_cache: dict[str, uuid.UUID | None] = {}

    async def asset_id(ref: str) -> uuid.UUID | None:
        key = ref.strip().lower()
        if key not in asset_cache:
            crypto = await market.resolve_asset(db, ref)
            asset_cache[key] = crypto.id if crypto else None
        return asset_cache[key]

    rows: list[ParsedRow] = []
    seen: set[str] = set()
    for number, raw in enumerate(reader, start=2):
        if len(rows) >= MAX_ROWS:
            return rows, [f"O arquivo excede {MAX_ROWS} linhas."]
        cells = {k: (v or "").strip() for k, v in raw.items() if k}
        if not any(cells.values()):
            continue
        row = ParsedRow(line=number, raw=cells)
        rows.append(row)
        try:
            kind = _TYPES.get(cells.get("tipo", "").lower())
            if kind is None:
                row.errors.append(f"tipo desconhecido: {cells.get('tipo')!r}")
            asset = await asset_id(cells.get("ativo", "")) if cells.get("ativo") else None
            if asset is None:
                row.errors.append(f"ativo não encontrado: {cells.get('ativo')!r}")
            to_asset = None
            if cells.get("ativo_destino"):
                to_asset = await asset_id(cells["ativo_destino"])
                if to_asset is None:
                    row.errors.append(
                        f"ativo de destino não encontrado: {cells['ativo_destino']!r}"
                    )
            for column in ("exchange", "exchange_destino"):
                if cells.get(column) and cells[column].lower() not in exchanges:
                    row.errors.append(f"exchange desconhecida: {cells[column]!r}")
            executed_at = parse_datetime(cells.get("data", ""), tz)
            values = {
                "quantity": parse_decimal(cells.get("quantidade", "")),
                "unit_price": parse_decimal(cells.get("preco_unitario", "")),
                "fee_amount": parse_decimal(cells.get("taxa", "")) or Decimal(0),
                "fee_quantity": parse_decimal(cells.get("taxa_no_ativo", "")) or Decimal(0),
                "to_quantity": parse_decimal(cells.get("quantidade_destino", "")),
            }
        except ValueError as exc:
            row.errors.append(str(exc))
            continue
        if row.errors:
            continue
        try:
            row.data = TransactionIn(
                type=kind,
                asset_id=asset,
                to_asset_id=to_asset,
                quote_currency=(cells.get("moeda") or "BRL").upper(),
                executed_at=executed_at,
                exchange_id=cells.get("exchange", "").lower() or None,
                to_exchange_id=cells.get("exchange_destino", "").lower() or None,
                notes=cells.get("observacoes") or None,
                **values,
            )
        except ValidationError as exc:
            row.errors.extend(err["msg"].removeprefix("Value error, ") for err in exc.errors())
            continue
        external = cells.get("id_externo") or _fingerprint(cells)
        row.external_id = external[:128]
        if row.external_id in existing or row.external_id in seen:
            row.duplicate = True
        seen.add(row.external_id)
    return rows, []
