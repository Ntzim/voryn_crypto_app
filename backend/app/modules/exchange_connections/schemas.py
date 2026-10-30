import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator

ConnectionStatus = Literal["active", "error", "blocked"]
RecordStatus = Literal["pending", "imported", "needs_review"]


class ConnectionIn(BaseModel):
    exchange_id: Literal["binance"]
    label: str = Field(default="Binance", min_length=1, max_length=80)
    # SecretStr keeps the credentials out of repr(), logs and error reports.
    api_key: SecretStr = Field(min_length=16, max_length=256)
    api_secret: SecretStr = Field(min_length=16, max_length=256)

    @field_validator("api_key", "api_secret", "label", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


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
