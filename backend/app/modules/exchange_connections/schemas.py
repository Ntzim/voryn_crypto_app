import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ConnectionStatus = Literal["active", "error", "blocked"]
RecordStatus = Literal["pending", "imported", "needs_review"]


class ConnectionIn(BaseModel):
    exchange_id: Literal["binance"]
    label: str = Field(default="Binance", min_length=1, max_length=80)
    api_key: str = Field(min_length=16, max_length=256)
    api_secret: str = Field(min_length=16, max_length=256)

    @field_validator("api_key", "api_secret", "label")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class ReconciliationRowOut(BaseModel):
    symbol: str
    asset_id: uuid.UUID | None
    exchange: Decimal
    voryn: Decimal
    difference: Decimal
    status: Literal["ok", "divergent"]


class ReconciliationOut(BaseModel):
    as_of: datetime
    ok: bool
    assets: list[ReconciliationRowOut]


class ConnectionOut(BaseModel):
    id: uuid.UUID
    exchange_id: str
    exchange_name: str
    label: str
    key_hint: str
    status: ConnectionStatus
    write_permissions: list[str]
    last_synced_at: datetime | None
    last_error: str | None
    created_at: datetime
    imported: int
    needs_review: int
    pending: int
    reconciliation: ReconciliationOut | None


class RecordOut(BaseModel):
    id: int
    kind: Literal["trade", "deposit", "withdrawal"]
    external_id: str
    occurred_at: datetime
    status: RecordStatus
    reason: str | None
    summary: str
