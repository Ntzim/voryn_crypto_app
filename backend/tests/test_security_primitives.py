import pyotp
import pytest

from app.core.crypto import decrypt, encrypt
from app.core.security import hash_password, hash_token, verify_password
from app.modules.auth import mfa
from app.modules.auth.passwords import validate_password_strength


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("a-long-passphrase")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "a-long-passphrase")
    assert not verify_password(hashed, "wrong-passphrase")


def test_verify_password_without_hash_is_false() -> None:
    # Unknown users still run a dummy verification and must never succeed.
    assert not verify_password(None, "anything-at-all")


def test_token_hash_is_deterministic_and_not_plaintext() -> None:
    assert hash_token("abc") == hash_token("abc")
    assert hash_token("abc") != hash_token("abd")
    assert "abc" not in hash_token("abc")


@pytest.mark.parametrize(
    "password", ["short", "aaaaaaaaaaaa", "1234567890", "Password123", "qwertyuiop"]
)
def test_weak_passwords_rejected(password: str) -> None:
    with pytest.raises(ValueError):
        validate_password_strength(password)


def test_strong_password_accepted() -> None:
    assert validate_password_strength("correct horse battery") == "correct horse battery"


def test_encryption_roundtrip_and_randomized() -> None:
    a, b = encrypt("seed"), encrypt("seed")
    assert a != b
    assert decrypt(a) == decrypt(b) == "seed"


def test_totp_accepts_one_step_drift_only() -> None:
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    now = 1_800_000_000
    assert mfa.matching_timecode(secret, totp.at(now), at=now) == now // 30
    assert mfa.matching_timecode(secret, totp.at(now - 30), at=now) is not None
    assert mfa.matching_timecode(secret, totp.at(now + 30), at=now) is not None
    assert mfa.matching_timecode(secret, totp.at(now - 90), at=now) is None
    assert mfa.matching_timecode(secret, "abcdef", at=now) is None


def test_recovery_codes_are_unique_and_normalized() -> None:
    codes = mfa.generate_recovery_codes()
    assert len(set(codes)) == mfa.RECOVERY_CODE_COUNT
    code = codes[0]
    assert mfa.hash_recovery_code(code) == mfa.hash_recovery_code(code.upper().replace("-", ""))


def test_blank_optional_secrets_are_treated_as_missing() -> None:
    from app.core.config import Settings

    settings = Settings(anthropic_api_key="", coingecko_api_key="  ")
    assert settings.anthropic_api_key is None and settings.coingecko_api_key is None


def test_exchange_credentials_never_appear_in_repr() -> None:
    from app.modules.exchange_connections.schemas import ConnectionIn

    body = ConnectionIn(
        exchange_id="binance", api_key="  " + "K" * 12 + "KEY-1234  ", api_secret="S" * 20 + "TOPSECRET"
    )
    assert "TOPSECRET" not in repr(body) and "KEY-1234" not in repr(body)
    assert "TOPSECRET" not in str(body.model_dump())
    assert body.api_key.get_secret_value().endswith("KEY-1234")  # still stripped


def test_error_reports_exclude_frame_locals(monkeypatch: pytest.MonkeyPatch) -> None:
    """Locals hold request bodies (passwords, exchange secrets) in model reprs."""
    import sentry_sdk

    from app.core.config import get_settings
    from app.main import create_app

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.example/1")
    get_settings.cache_clear()
    try:
        create_app()
    finally:
        get_settings.cache_clear()
    assert calls and calls[0]["include_local_variables"] is False
    assert calls[0]["send_default_pii"] is False
