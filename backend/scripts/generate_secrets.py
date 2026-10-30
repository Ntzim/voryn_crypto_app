"""Print fresh production secrets (paste them as Railway shared variables).

    cd backend && uv run python scripts/generate_secrets.py

Never commit the output. Generate once per environment; rotating SECRET_KEY signs every
user out, and ENCRYPTION_KEYS must keep the old key (comma-separated, new key first) until
stored secrets are re-encrypted.
"""

import secrets

from cryptography.fernet import Fernet

print(f"SECRET_KEY={secrets.token_urlsafe(48)}")
print(f"ENCRYPTION_KEYS={Fernet.generate_key().decode()}")
