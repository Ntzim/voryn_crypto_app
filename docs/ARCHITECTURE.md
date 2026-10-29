# Arquitetura da Voryn

> Estado: Fases 1 a 4 concluídas. Este documento descreve a arquitetura alvo e marca o que já existe.

## Visão geral

```
Navegador ──HTTPS──▶ web (Next.js 16, App Router)
                      │  ├─ páginas (RSC + client components)
                      │  └─ /api/* → BFF proxy (route handler) ──HTTP interno──▶ api (FastAPI)
                      │                                                         │
                      │                                        ┌────────────────┼──────────────┐
                      │                                        ▼                ▼              ▼
                      │                                   PostgreSQL          Redis       Provedores
                      │                                   (dados)      (rate limit, MFA,   externos
                      │                                                 broker Celery)    (CoinGecko)
                      │                                                        ▲
                      └────────────────────────────── worker + beat (Celery) ──┘
```

- **Monólito modular** no backend: um único deploy FastAPI com módulos de domínio isolados. Sem microsserviços até haver motivo mensurável (escala independente, time separado).
- **BFF (Backend for Frontend)**: o navegador só fala com a origem do Next.js. O route handler `src/app/api/[...path]/route.ts` repassa as chamadas para a API em tempo de execução. Benefícios: cookies first-party (`SameSite=Lax`), nenhuma configuração de CORS em produção, API pode ficar em rede privada.
- **Worker Celery** para tudo que não deve bloquear uma requisição: sincronização de mercado, câmbio, envio de e-mail, limpeza/retenção. O `beat` agenda as tarefas periódicas.

## Backend (`backend/`)

| Camada | Onde | Responsabilidade |
|---|---|---|
| Núcleo | `app/core/` | config (pydantic-settings), DB (SQLAlchemy 2 async), Redis, logs estruturados (structlog), envelope de erros, middleware (request id, CSRF, rate limit global, security headers), criptografia (Fernet), e-mail |
| Módulos | `app/modules/<domínio>/` | `models.py` (ORM), `schemas.py` (contratos Pydantic), `service.py` (casos de uso), `router.py` (HTTP fino) |
| Jobs | `app/worker.py` | tarefas Celery como wrappers síncronos dos serviços async |
| Migrations | `alembic/` | versionamento do schema |

Regras de dependência:

1. `router` → `service` → `models`. Routers não contêm regra de negócio.
2. Módulos conversam por funções de serviço públicas, nunca acessando tabelas de outro módulo diretamente (exceção atual: `auth` lê/escreve `users`, que é seu agregado).
3. Integrações externas ficam atrás de um `Protocol` (ex.: `MarketDataProvider`). Trocar a CoinGecko não toca serviços nem API.
4. A futura camada de IA (Fase 5) seguirá o mesmo padrão: `LLMProvider` como protocolo, prompts e ferramentas no módulo `ai_insights`, consumindo **apenas** saídas estruturadas dos motores determinísticos.

### Módulos

| Módulo | Fase | Estado |
|---|---|---|
| `auth` — cadastro, login, 2FA, sessões, e-mails transacionais | 1 | ✅ |
| `users` — perfil e preferências (User Settings) | 1 | ✅ |
| `audit` — trilha de auditoria append-only | 1 | ✅ |
| `market_data` — catálogo, cotações, câmbio, provedores | 1 | ✅ (inicial) |
| `health` — liveness/readiness | 1 | ✅ |
| `portfolio` — transações, motor de posição, rentabilidade, insights, CSV ([metodologia](PORTFOLIO.md)) | 2 | ✅ |
| `technical_analysis` — indicadores, tendência, níveis ([metodologia](TECHNICAL_ANALYSIS.md)) | 3 | ✅ |
| `watchlists` — favoritos e listas | 3 | ✅ |
| `signals` — score, classificação, histórico ([metodologia](SIGNALS.md)) | 4 | ✅ |
| `alerts` — alertas, notificações, canais | 4 | ✅ |
| `ai` — Voryn AI: provedor de LLM, ferramentas, conversas, SSE ([metodologia](AI.md)) | 5 | ✅ |
| `risk`, `backtesting`, `exchange_connections` | 6 | — |

### Dados de mercado

- Cotações ingeridas **uma vez em USD** (fonte única da verdade). BRL é derivado com a última taxa USD→BRL armazenada; toda resposta informa `fx_rate`, `fx_observed_at` e `change_basis: "USD"` (variações percentuais são calculadas pelo provedor em USD).
- Toda resposta de mercado carrega `status.fetched_at` e `status.is_stale` (padrão: > 15 min). A UI exibe o aviso quando os dados estão desatualizados — requisito para sinais na Fase 4.
- Linhas inválidas do provedor (preço negativo/ausente, timestamp no futuro, JSON malformado) são descartadas e logadas, nunca persistidas.
- Números JSON são lidos como `Decimal` (sem arredondamento de float).
- Limites: o plano Demo gratuito da CoinGecko permite ~10 mil chamadas/mês. Padrões (mercado a cada 5 min, câmbio a cada 1 h) ≈ 9,4 mil chamadas/mês. Ajuste `MARKET_SYNC_INTERVAL_SECONDS` conforme o plano.
- Atribuição "Dados fornecidos por CoinGecko" exibida na interface, conforme os termos de uso.

### Sessões e autenticação

Ver [SECURITY.md](SECURITY.md). Resumo: sessões opacas no servidor (cookie `HttpOnly`), CSRF double-submit, argon2id, TOTP com proteção a replay, códigos de recuperação, rate limiting por IP e por conta.

## Frontend (`frontend/`)

- **Next.js 16 App Router + TypeScript estrito + Tailwind CSS v4 + shadcn/ui** (componentes copiados para `src/components/ui`, tematizados com os tokens Voryn).
- **TanStack Query** para estado de servidor (cache, revalidação, estados de loading/erro). **Zustand** apenas para estado de UI persistente (sidebar recolhida).
- Tipos da API gerados a partir do OpenAPI do backend (`npm run gen:api` → `src/lib/api/schema.d.ts`), evitando duplicação manual de contratos.
- `src/proxy.ts` (antigo `middleware.ts`) redireciona rotas protegidas sem cookie de sessão para `/entrar`. A validação real da sessão é sempre feita pela API.
- Valores monetários chegam como **strings decimais**; o frontend apenas formata (via `Intl.NumberFormat`), nunca calcula valores financeiros.

### Navegação responsiva

| Largura | Navegação |
|---|---|
| < 768 px (smartphone) | barra inferior com Dashboard, Carteira, Mercado, Oportunidades e "Mais" (sheet com o restante) |
| 768–1279 px (tablet/notebook) | trilho lateral só com ícones |
| ≥ 1280 px (desktop) | sidebar completa, recolhível |

Páginas de fases futuras existem na navegação e mostram um estado vazio honesto ("disponível na Fase N"), sem dados fictícios ou controles sem implementação.

## Infraestrutura

- `docker-compose.yml`: postgres, redis, mailpit (SMTP de desenvolvimento), migrate, api, worker, beat, web. Portas do host configuráveis (`VORYN_*_PORT`).
- **Railway**: um serviço por processo (web, api, worker, beat) a partir dos mesmos Dockerfiles; Postgres e Redis gerenciados. A API pode ficar só na rede privada; o web aponta `API_INTERNAL_URL` para ela. Migrations rodam como *pre-deploy command* (`alembic upgrade head`).
- **CI (GitHub Actions)**: lint (ruff, eslint), tipos (mypy strict, tsc), testes (pytest com Postgres real), verificação de migrations (`alembic check`), build do frontend.
- **Observabilidade**: logs JSON com `request_id` (propagado no header `X-Request-ID`), Sentry opcional (`SENTRY_DSN`), `/health/live` e `/health/ready`.
