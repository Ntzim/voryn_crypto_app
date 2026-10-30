import re
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


# Links, domains and e-mail addresses. The name is printed in e-mails sent to the address
# given at sign-up, which need not belong to whoever signs up: a "name" such as
# "Conta bloqueada, acesse www.example.com" would reach that inbox from Voryn's domain,
# and mail clients turn the domain into a link.
_LINK_LIKE = re.compile(r"[<>@/\\]|:/|www\.|[a-z0-9-]\.[a-z]{2,}", re.IGNORECASE)


def validate_full_name(value: str) -> str:
    value = " ".join(value.split())
    if len(value) < 2:
        raise ValueError("Informe seu nome.")
    if _LINK_LIKE.search(value):
        raise ValueError("O nome não pode conter links, e-mails ou endereços de sites.")
    return value


class ProfileUpdateIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)

    @field_validator("full_name")
    @classmethod
    def _name(cls, value: str) -> str:
        return validate_full_name(value)


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
