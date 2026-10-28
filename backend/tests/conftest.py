"""Test harness: real PostgreSQL (separate `voryn_test` database), in-memory Redis and e-mail."""

import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": os.environ.get(
            "TEST_DATABASE_URL", "postgresql+asyncpg://voryn:voryn@localhost:5442/voryn_test"
        ),
        "EMAIL_BACKEND": "memory",
        "EMAIL_DELIVERY": "inline",
        "COOKIE_SECURE": "false",
        "LOG_JSON": "false",
        "LOG_LEVEL": "WARNING",
        "SECRET_KEY": "test-secret-key-test-secret-key-0123456789",
    }
)

import fakeredis
import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.core.db import dispose_engine, get_engine, get_sessionmaker
from app.core.email import EmailMessage, MemoryBackend, set_email_backend
from app.core.redis import set_redis
from app.main import create_app
from app.models import Base

API = "/api/v1"
Outbox = list[EmailMessage]
ClientFactory = Callable[[], Awaitable[httpx.AsyncClient]]
PASSWORD = "correct-horse-battery"


async def _ensure_database() -> None:
    url = make_url(get_settings().database_url)
    admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
        )
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    await admin.dispose()


@pytest.fixture(scope="session", autouse=True)
async def database() -> AsyncIterator[None]:
    await _ensure_database()
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await dispose_engine()


@pytest.fixture(autouse=True)
async def _clean_state() -> AsyncIterator[None]:
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    set_redis(redis)
    yield
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with get_engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    await redis.flushall()
    set_redis(None)


@pytest.fixture
def outbox() -> Iterator[Outbox]:
    backend = MemoryBackend()
    set_email_backend(backend)
    yield backend.outbox
    set_email_backend(None)


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


async def _new_client() -> httpx.AsyncClient:
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://testserver"
    )
    response = await client.get(f"{API}/auth/csrf")
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    c = await _new_client()
    yield c
    await c.aclose()


@pytest.fixture
async def client_factory() -> AsyncIterator[ClientFactory]:
    created: list[httpx.AsyncClient] = []

    async def make() -> httpx.AsyncClient:
        c = await _new_client()
        created.append(c)
        return c

    yield make
    for c in created:
        await c.aclose()


def extract_token(message_text: str) -> str:
    match = re.search(r"token=([A-Za-z0-9_\-]+)", message_text)
    assert match, message_text
    return match.group(1)


async def register_verified(
    client: httpx.AsyncClient,
    outbox: Outbox,
    email: str = "ana@example.com",
    password: str = PASSWORD,
    name: str = "Ana Souza",
) -> None:
    response = await client.post(
        f"{API}/auth/register", json={"email": email, "password": password, "full_name": name}
    )
    assert response.status_code == 202, response.text
    token = extract_token(outbox[-1].text)
    response = await client.post(f"{API}/auth/email/verify", json={"token": token})
    assert response.status_code == 200, response.text


async def login(
    client: httpx.AsyncClient, email: str = "ana@example.com", password: str = PASSWORD
) -> httpx.Response:
    return await client.post(f"{API}/auth/login", json={"email": email, "password": password})
