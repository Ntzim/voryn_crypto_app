# syntax=docker/dockerfile:1.7
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app

FROM base AS deps
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

FROM base AS runtime
RUN useradd --system --uid 10001 --home /app voryn
COPY --from=deps /opt/venv /opt/venv
COPY --chown=voryn:voryn alembic.ini ./
COPY --chown=voryn:voryn alembic ./alembic
COPY --chown=voryn:voryn app ./app
USER voryn
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health/live', timeout=3)"
# Railway injects $PORT; HOST=:: listens dual-stack (IPv6 + IPv4) for its private network.
# Client IPs are resolved by the app (TRUST_PROXY_HEADERS), not uvicorn.
# The same image runs the worker and beat with another start command (docs/DEPLOY.md).
CMD ["python", "-m", "app.serve"]
