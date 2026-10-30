import time

import httpx
import pyotp
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.users.models import User
from tests.conftest import (
    API,
    PASSWORD,
    ClientFactory,
    Outbox,
    extract_token,
    login,
    register_verified,
)


async def test_full_registration_flow(client: httpx.AsyncClient, outbox: Outbox) -> None:
    response = await client.post(
        f"{API}/auth/register",
        json={"email": " Ana@Example.com ", "password": PASSWORD, "full_name": "  Ana   Souza "},
    )
    assert response.status_code == 202
    assert len(outbox) == 1
    assert "/verificar-email?token=" in outbox[0].text

    # Correct password but unverified e-mail: explicit, actionable error.
    response = await login(client)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "email_not_verified"

    token = extract_token(outbox[0].text)
    assert (await client.post(f"{API}/auth/email/verify", json={"token": token})).status_code == 200
    # Tokens are single use.
    assert (await client.post(f"{API}/auth/email/verify", json={"token": token})).status_code == 400

    response = await login(client)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "authenticated"
    assert body["user"]["email"] == "ana@example.com"
    assert body["user"]["full_name"] == "Ana Souza"
    assert body["user"]["settings"] == {
        "base_currency": "BRL",
        "locale": "pt-BR",
        "timezone": "America/Sao_Paulo",
    }
    cookie = response.headers["set-cookie"]
    assert "voryn_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie

    me = await client.get(f"{API}/me")
    assert me.status_code == 200 and me.json()["email_verified"] is True

    assert (await client.post(f"{API}/auth/logout")).status_code == 204
    assert (await client.get(f"{API}/me")).status_code == 401


async def test_duplicate_registration_does_not_reveal_account(
    client: httpx.AsyncClient,
    outbox: Outbox,
    db: AsyncSession,
) -> None:
    await register_verified(client, outbox)
    response = await client.post(
        f"{API}/auth/register",
        json={"email": "ana@example.com", "password": "another-passphrase", "full_name": "X Y"},
    )
    assert response.status_code == 202
    assert outbox[-1].subject == "Tentativa de cadastro na Voryn"
    assert await db.scalar(select(func.count()).select_from(User)) == 1


@pytest.mark.parametrize(
    "name",
    [
        "Conta bloqueada, acesse www.voryn-suporte.com",
        "Ana https://evil.example",
        "Ana evil.example",
        "Ana <b>Souza</b>",
        "Ana suporte@evil.example",
    ],
)
async def test_link_like_names_are_rejected(
    client: httpx.AsyncClient, outbox: Outbox, name: str
) -> None:
    """The name is printed in an e-mail sent to whatever address is given at sign-up."""
    response = await client.post(
        f"{API}/auth/register",
        json={"email": "victim@example.com", "password": PASSWORD, "full_name": name},
    )
    assert response.status_code == 422
    assert outbox == []

    await register_verified(client, outbox)
    await login(client)
    assert (await client.patch(f"{API}/me", json={"full_name": name})).status_code == 422


async def test_ordinary_names_are_accepted(client: httpx.AsyncClient, outbox: Outbox) -> None:
    await register_verified(client, outbox, name="Maria-José D'Ávila J. R. Souza")
    await login(client)
    assert (await client.get(f"{API}/me")).json()["full_name"] == "Maria-José D'Ávila J. R. Souza"


async def test_weak_password_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"{API}/auth/register",
        json={"email": "a@example.com", "password": "1234567890", "full_name": "Ana"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_login_failures_are_throttled_per_account(
    client: httpx.AsyncClient,
    outbox: Outbox,
    db: AsyncSession,
) -> None:
    await register_verified(client, outbox)
    for _ in range(5):
        response = await login(client, password="wrong-password-x")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"
    # Even the right password is refused while the account is cooling down.
    response = await login(client)
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0
    failures = await db.scalar(select(func.count()).where(AuditLog.action == "auth.login_failed"))
    assert failures == 5


async def test_unknown_email_and_wrong_password_look_identical(client: httpx.AsyncClient) -> None:
    response = await login(client, email="nobody@example.com")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


async def test_csrf_header_is_required(client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"{API}/auth/login",
        json={"email": "a@example.com", "password": "x"},
        headers={"X-CSRF-Token": "forged"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


async def test_password_reset_flow(
    client: httpx.AsyncClient,
    client_factory: ClientFactory,
    outbox: Outbox,
) -> None:
    await register_verified(client, outbox)
    assert (await login(client)).status_code == 200

    sent_before = len(outbox)
    response = await client.post(
        f"{API}/auth/password/forgot", json={"email": "nobody@example.com"}
    )
    assert response.status_code == 202
    assert len(outbox) == sent_before  # unknown e-mail: same answer, nothing sent

    anon = await client_factory()
    assert (
        await anon.post(f"{API}/auth/password/forgot", json={"email": "ana@example.com"})
    ).status_code == 202
    token = extract_token(outbox[-1].text)
    response = await anon.post(
        f"{API}/auth/password/reset", json={"token": token, "new_password": "brand-new-passphrase"}
    )
    assert response.status_code == 200

    # Existing sessions were revoked, the old password no longer works.
    assert (await client.get(f"{API}/me")).status_code == 401
    assert (await login(anon)).status_code == 401
    assert (await login(anon, password="brand-new-passphrase")).status_code == 200
    # Reset links are single use.
    response = await anon.post(
        f"{API}/auth/password/reset", json={"token": token, "new_password": "another-passphrase"}
    )
    assert response.status_code == 400


async def test_change_password_keeps_current_session_only(
    client: httpx.AsyncClient,
    client_factory: ClientFactory,
    outbox: Outbox,
) -> None:
    await register_verified(client, outbox)
    other = await client_factory()
    assert (await login(client)).status_code == 200
    assert (await login(other)).status_code == 200

    response = await client.post(
        f"{API}/me/password",
        json={"current_password": "wrong-password-x", "new_password": "brand-new-passphrase"},
    )
    assert response.status_code == 401

    response = await client.post(
        f"{API}/me/password",
        json={"current_password": PASSWORD, "new_password": "brand-new-passphrase"},
    )
    assert response.status_code == 204
    assert (await client.get(f"{API}/me")).status_code == 200
    assert (await other.get(f"{API}/me")).status_code == 401


async def test_sessions_are_isolated_between_users(
    client: httpx.AsyncClient,
    client_factory: ClientFactory,
    outbox: Outbox,
) -> None:
    await register_verified(client, outbox)
    assert (await login(client)).status_code == 200
    mallory = await client_factory()
    await register_verified(mallory, outbox, email="mallory@example.com", name="Mallory")
    assert (await login(mallory, email="mallory@example.com")).status_code == 200

    sessions = (await client.get(f"{API}/me/sessions")).json()
    assert len(sessions) == 1 and sessions[0]["current"] is True
    victim_session = sessions[0]["id"]

    response = await mallory.delete(f"{API}/me/sessions/{victim_session}")
    assert response.status_code == 404
    assert (await client.get(f"{API}/me")).status_code == 200


async def test_profile_and_settings_update(
    client: httpx.AsyncClient,
    outbox: Outbox,
) -> None:
    await register_verified(client, outbox)
    await login(client)
    response = await client.patch(f"{API}/me", json={"full_name": "Ana S. Lima"})
    assert response.status_code == 200 and response.json()["full_name"] == "Ana S. Lima"

    response = await client.patch(
        f"{API}/me/settings", json={"base_currency": "USD", "timezone": "Europe/Lisbon"}
    )
    assert response.status_code == 200
    assert response.json()["base_currency"] == "USD"
    for invalid in ({"timezone": "Mars/Base"}, {"base_currency": "EUR"}):
        assert (await client.patch(f"{API}/me/settings", json=invalid)).status_code == 422


async def test_two_factor_lifecycle(
    client: httpx.AsyncClient,
    outbox: Outbox,
) -> None:
    await register_verified(client, outbox)
    await login(client)

    setup = (await client.post(f"{API}/me/mfa/setup")).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/Voryn")
    totp = pyotp.TOTP(setup["secret"])

    assert (await client.post(f"{API}/me/mfa/enable", json={"code": "000000"})).status_code == 401
    enabled = await client.post(f"{API}/me/mfa/enable", json={"code": totp.now()})
    assert enabled.status_code == 200
    recovery_codes = enabled.json()["recovery_codes"]
    assert len(recovery_codes) == 10
    assert (await client.get(f"{API}/me")).json()["mfa_enabled"] is True

    await client.post(f"{API}/auth/logout")
    challenge = (await login(client)).json()
    assert challenge["status"] == "mfa_required" and challenge["user"] is None
    assert (await client.get(f"{API}/me")).status_code == 401  # no session before 2nd factor

    mfa_token = challenge["mfa_token"]
    response = await client.post(
        f"{API}/auth/login/mfa", json={"mfa_token": mfa_token, "code": "123456"}
    )
    assert response.status_code == 401
    # The current step was consumed when enabling; the next step is inside the drift window.
    next_code = totp.at(int(time.time()) + 30)
    response = await client.post(
        f"{API}/auth/login/mfa", json={"mfa_token": mfa_token, "code": next_code}
    )
    assert response.status_code == 200 and response.json()["status"] == "authenticated"

    # Replay of the same code is rejected, even with a fresh challenge.
    await client.post(f"{API}/auth/logout")
    mfa_token = (await login(client)).json()["mfa_token"]
    response = await client.post(
        f"{API}/auth/login/mfa", json={"mfa_token": mfa_token, "code": next_code}
    )
    assert response.status_code == 401

    # Recovery codes work exactly once.
    response = await client.post(
        f"{API}/auth/login/mfa", json={"mfa_token": mfa_token, "code": recovery_codes[0]}
    )
    assert response.status_code == 200
    await client.post(f"{API}/auth/logout")
    mfa_token = (await login(client)).json()["mfa_token"]
    response = await client.post(
        f"{API}/auth/login/mfa", json={"mfa_token": mfa_token, "code": recovery_codes[0]}
    )
    assert response.status_code == 401
    response = await client.post(
        f"{API}/auth/login/mfa", json={"mfa_token": mfa_token, "code": recovery_codes[1]}
    )
    assert response.status_code == 200

    # Disabling requires both password and a second factor.
    response = await client.post(
        f"{API}/me/mfa/disable", json={"password": PASSWORD, "code": "000000"}
    )
    assert response.status_code == 401
    response = await client.post(
        f"{API}/me/mfa/disable", json={"password": PASSWORD, "code": recovery_codes[2]}
    )
    assert response.status_code == 204
    assert (await login(client)).json()["status"] == "authenticated"


async def test_mfa_challenge_attempts_are_limited(
    client: httpx.AsyncClient,
    outbox: Outbox,
) -> None:
    await register_verified(client, outbox)
    await login(client)
    secret = (await client.post(f"{API}/me/mfa/setup")).json()["secret"]
    await client.post(f"{API}/me/mfa/enable", json={"code": pyotp.TOTP(secret).now()})
    await client.post(f"{API}/auth/logout")

    mfa_token = (await login(client)).json()["mfa_token"]
    for _ in range(5):
        response = await client.post(
            f"{API}/auth/login/mfa", json={"mfa_token": mfa_token, "code": "000000"}
        )
        assert response.status_code == 401
    response = await client.post(
        f"{API}/auth/login/mfa", json={"mfa_token": mfa_token, "code": "000000"}
    )
    assert response.status_code == 429


async def test_mfa_failures_are_limited_per_account_across_challenges(
    client: httpx.AsyncClient,
    outbox: Outbox,
) -> None:
    """A fresh challenge only costs the password, so the cap must span challenges."""
    await register_verified(client, outbox)
    await login(client)
    totp = pyotp.TOTP((await client.post(f"{API}/me/mfa/setup")).json()["secret"])
    await client.post(f"{API}/me/mfa/enable", json={"code": totp.now()})
    await client.post(f"{API}/auth/logout")
    outbox.clear()

    for _ in range(2):  # two challenges, each within its own 5-attempt cap
        mfa_token = (await login(client)).json()["mfa_token"]
        for _ in range(5):
            response = await client.post(
                f"{API}/auth/login/mfa", json={"mfa_token": mfa_token, "code": "000000"}
            )
            assert response.status_code == 401

    # Even the correct code is refused until the window passes.
    mfa_token = (await login(client)).json()["mfa_token"]
    code = totp.at(int(time.time()) + 30)
    response = await client.post(
        f"{API}/auth/login/mfa", json={"mfa_token": mfa_token, "code": code}
    )
    assert response.status_code == 429

    # The owner is warned once: reaching the second factor required the password.
    notices = [m for m in outbox if m.subject == "Alerta de segurança da Voryn"]
    assert len(notices) == 1
    assert "errou o código" in notices[0].text
