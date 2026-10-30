"""Every API route requires a session unless it is listed as public on purpose.

Walks the real route table, so a new endpoint that forgets its CurrentAuth dependency
fails here instead of shipping unauthenticated.
"""

import re
import uuid

import httpx

from app.main import create_app
from tests.conftest import API

#: Reachable without a session: sign-up, sign-in and recovery flows.
PUBLIC = {
    ("GET", "/api/v1/auth/csrf"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/email/verify"),
    ("POST", "/api/v1/auth/email/resend"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/login/mfa"),
    ("POST", "/api/v1/auth/password/forgot"),
    ("POST", "/api/v1/auth/password/reset"),
}


def _api_routes() -> list[tuple[str, str]]:
    # The OpenAPI document lists every mounted route, including nested routers.
    paths = create_app().openapi()["paths"]
    routes = [
        (method.upper(), path)
        for path, operations in paths.items()
        if path.startswith(API)
        for method in operations
    ]
    assert len(routes) > 50, routes  # guard against an empty walk passing vacuously
    return routes


def _concrete(path: str) -> str:
    def fill(match: re.Match[str]) -> str:
        name = match.group(1)
        if name == "notification_id":
            return "1"
        if name == "slug":
            return "bitcoin"
        return str(uuid.uuid4())

    return re.sub(r"\{(\w+)\}", fill, path)


async def test_public_routes_exist() -> None:
    """Keeps the allowlist honest: a renamed public route must be renamed here too."""
    assert set(_api_routes()) >= PUBLIC


async def test_every_other_route_requires_a_session(client: httpx.AsyncClient) -> None:
    client.cookies.pop("voryn_session", None)
    unprotected = []
    for method, path in _api_routes():
        if (method, path) in PUBLIC:
            continue
        response = await client.request(method, _concrete(path), json={})
        if response.status_code != 401:
            unprotected.append(f"{method} {path} -> {response.status_code}")
    assert unprotected == []
