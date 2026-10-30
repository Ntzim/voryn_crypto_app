import uuid
import zoneinfo
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.auth.passwords import validate_password_strength

Currency = Literal["BRL", "USD"]
Locale = Literal["pt-BR", "en-US"]


class UserSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    base_currency: Currency
    locale: Locale
    timezone: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    email_verified: bool
    mfa_enabled: bool
    created_at: datetime
    settings: UserSettingsOut


class ProfileUpdateIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)

    @field_validator("full_name")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Informe seu nome.")
        return value


class SettingsUpdateIn(BaseModel):
    base_currency: Currency | None = None
    locale: Locale | None = None
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str | None) -> str | None:
        if value is not None and value not in zoneinfo.available_timezones():
            raise ValueError("Fuso horário inválido.")
        return value


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)

    @field_validator("new_password")
    @classmethod
    def _strong(cls, value: str) -> str:
        return validate_password_strength(value)


class SessionOut(BaseModel):
    id: uuid.UUID
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    current: bool
