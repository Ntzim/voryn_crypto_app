# VORYN — Crypto Intelligence Platform

> Intelligence Behind Every Trade.

Plataforma de inteligência para investimentos em criptomoedas: patrimônio, mercado, análise técnica, sinais quantitativos transparentes e um assistente de IA que só interpreta dados calculados pela própria plataforma.

**Estado atual: Fase 3 — Inteligência de mercado** (candles 15m–1w, indicadores técnicos determinísticos, tendência, suportes/resistências, watchlists), sobre a carteira funcional (Fase 2) e a fundação (Fase 1). Plano completo em [docs/ROADMAP.md](docs/ROADMAP.md).

## Stack

| Camada | Tecnologias |
|---|---|
| Frontend | Next.js 16 (App Router, Cache Components), TypeScript estrito, Tailwind CSS v4, shadcn/ui (Radix), TanStack Query, Zustand |
| Backend | Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic, Celery |
| Dados | PostgreSQL 17, Redis 7 |
| Mercado | CoinGecko (cotações), Binance dados públicos (candles), BCB PTAX (câmbio) — atrás de interfaces de provedor substituíveis |
| Infra | Docker / Docker Compose, GitHub Actions, pronto para Railway |

## Rodando localmente

Pré-requisito: Docker Desktop.

```bash
cp .env.example .env        # opcional: chave CoinGecko e portas
docker compose up --build
```

| Serviço | URL |
|---|---|
| Aplicação | http://localhost:3010 |
| API (docs OpenAPI) | http://localhost:8010/docs |
| E-mails de desenvolvimento (Mailpit) | http://localhost:8035 |

Crie uma conta em `/criar-conta`; o link de confirmação chega no Mailpit. O worker sincroniza o mercado ao iniciar e depois a cada 5 minutos.

> No Windows/macOS, o hot reload do serviço `web` dentro do Docker pode não detectar alterações (bind mounts não propagam eventos de arquivo). Para desenvolver o frontend, prefira `npm run dev` no host (abaixo) ou `docker compose restart web`.

As portas do host usam valores incomuns (3010, 8010, 5442, 6389, 8035) para não colidir com outros projetos; altere com `VORYN_*_PORT` no `.env`.

### Desenvolvimento fora do Docker

```bash
docker compose up -d postgres redis mailpit

cd backend
cp .env.example .env          # preencha SECRET_KEY/ENCRYPTION_KEYS se quiser
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8010
uv run celery -A app.worker.celery_app worker -B -Q voryn --loglevel=INFO   # outro terminal

cd ../frontend
npm install
npm run dev -- --port 3010    # API_INTERNAL_URL padrão: http://localhost:8010
```

## Qualidade

```bash
# backend
uv run ruff check . && uv run ruff format --check .
uv run mypy app tests          # strict
uv run pytest                  # usa Postgres real (banco voryn_test)
uv run alembic check           # modelos e migrations em sincronia

# frontend
npm run lint && npm run typecheck && npm test && npm run build
npm run test:e2e               # Playwright, com a stack do docker compose no ar
```

### Contratos de API

Os tipos TypeScript são gerados do OpenAPI do backend:

```bash
cd backend && PYTHONPATH=. uv run python scripts/export_openapi.py ../frontend/openapi.json
cd ../frontend && npm run gen:api
```

## Deploy (Railway)

Um serviço por processo, a partir dos Dockerfiles do repositório:

| Serviço | Origem | Comando |
|---|---|---|
| `web` | `frontend/` (target `runtime`) | padrão (`node server.js`) — defina `API_INTERNAL_URL` com o endereço privado da API |
| `api` | `backend/` | padrão; *pre-deploy*: `alembic upgrade head` |
| `worker` | `backend/` | `celery -A app.worker.celery_app worker -Q voryn` |
| `beat` | `backend/` | `celery -A app.worker.celery_app beat` |

Plugins: PostgreSQL e Redis. Variáveis obrigatórias da API em produção (ela se recusa a iniciar sem elas): `ENVIRONMENT=production`, `SECRET_KEY`, `ENCRYPTION_KEYS`, `DATABASE_URL`, `REDIS_URL`, `FRONTEND_URL`, `EMAIL_BACKEND=smtp` + `SMTP_*`, `TRUST_PROXY_HEADERS=true`. Opcionais: `COINGECKO_API_KEY`, `SENTRY_DSN`.

## Documentação

- [Arquitetura](docs/ARCHITECTURE.md)
- [Modelo de dados](docs/DATA_MODEL.md)
- [Carteira: metodologia de cálculo](docs/PORTFOLIO.md)
- [Análise técnica: metodologia](docs/TECHNICAL_ANALYSIS.md)
- [Segurança](docs/SECURITY.md)
- [Decisões técnicas](docs/DECISIONS.md)
- [Plano de implementação](docs/ROADMAP.md)

## Aviso

A Voryn não promete lucros. Indicadores, scores e análises são informativos, baseados em dados históricos, e não constituem recomendação de investimento.
