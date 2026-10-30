"""Exchange connector contract: read-only access to balances and account history."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Protocol

RecordKind = Literal["trade", "deposit", "withdrawal"]


class ConnectorError(Exception):
    """The exchange could not be reached or answered unexpectedly (retry later)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ConnectorAuthError(ConnectorError):
    """The credentials were rejected (invalid, expired or revoked)."""


@dataclass(frozen=True, slots=True)
class Permissions:
    can_read: bool
    #: every permission beyond reading, by the exchange's own name, that is enabled
    write_permissions: list[str]

    @property
    def read_only(self) -> bool:
        return self.can_read and not self.write_permissions


@dataclass(frozen=True, slots=True)
class ExternalRecord:
    kind: RecordKind
    #: stable id at the exchange, unique per connection (used for deduplication)
    external_id: str
    occurred_at: datetime
    data: dict[str, Any]


@dataclass(slots=True)
class SyncBatch:
    records: list[ExternalRecord] = field(default_factory=list)
    #: opaque incremental position, stored and handed back on the next sync
    cursor: dict[str, Any] = field(default_factory=dict)


class ExchangeConnector(Protocol):
    exchange_id: str

    async def permissions(self) -> Permissions: ...

    async def balances(self) -> dict[str, Decimal]:
        """Total (free + locked) per asset symbol, zero balances omitted."""
        ...

    async def history(self, cursor: dict[str, Any], assets: Sequence[str]) -> SyncBatch:
        """Records newer than `cursor`. `assets` are symbols known to matter (balances,
        earlier records) so the connector can limit per-market queries."""
        ...

    async def aclose(self) -> None: ...
