from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, EmailStr, Field, field_validator

from app.modules.auth.passwords import validate_password_strength
from app.modules.users.schemas import UserOut, validate_full_name


def _normalize_email(value: str) -> str:
    return value.strip().lower()


Email = Annotated[EmailStr, Field(max_length=254), AfterValidator(_normalize_email)]


class RegisterIn(BaseModel):
    email: Email
    password: str = Field(max_length=128)
    full_name: str = Field(min_length=2, max_length=120)

    @field_validator("password")
    @classmethod
    def _strong(cls, value: str) -> str:
        return validate_password_strength(value)

    @field_validator("full_name")
    @classmethod
    def _name(cls, value: str) -> str:
        return validate_full_name(value)


class LoginIn(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=128)


class MfaLoginIn(BaseModel):
    mfa_token: str = Field(min_length=16, max_length=128)
    code: str = Field(min_length=6, max_length=32)


class LoginOut(BaseModel):
    status: Literal["authenticated", "mfa_required"]
    user: UserOut | None = None
    mfa_token: str | None = None


class EmailIn(BaseModel):
    email: Email


class TokenIn(BaseModel):
    token: str = Field(min_length=16, max_length=128)


class PasswordResetIn(BaseModel):
    token: str = Field(min_length=16, max_length=128)
    new_password: str = Field(max_length=128)

    @field_validator("new_password")
    @classmethod
    def _strong(cls, value: str) -> str:
        return validate_password_strength(value)


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class MfaCodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class MfaEnableOut(BaseModel):
    recovery_codes: list[str]


class MfaDisableIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=6, max_length=32)


class MessageOut(BaseModel):
    message: str


class CsrfOut(BaseModel):
    csrf_token: str
