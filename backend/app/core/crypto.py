"""Symmetric encryption for secrets at rest (TOTP seeds, future exchange API keys).

Uses MultiFernet so keys can be rotated: the first key in ENCRYPTION_KEYS encrypts,
every configured key is tried on decrypt.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings


class DecryptionError(Exception):
    pass


@lru_cache
def _fernet() -> MultiFernet:
    settings = get_settings()
    keys = [k.get_secret_value() for k in settings.encryption_keys]
    if not keys:
        if settings.is_production:
            raise RuntimeError("ENCRYPTION_KEYS is required in production")
        # Deterministic development key derived from SECRET_KEY; never used in production.
        import base64
        import hashlib

        digest = hashlib.sha256(settings.secret_key.get_secret_value().encode()).digest()
        keys = [base64.urlsafe_b64encode(digest).decode()]
    return MultiFernet([Fernet(k) for k in keys])


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError("Unable to decrypt value with configured keys") from exc
