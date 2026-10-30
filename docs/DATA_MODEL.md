# Modelo de dados

Princípios:

- **PostgreSQL**, chaves `UUID` para entidades expostas na API e `BIGINT IDENTITY` para séries temporais/append-only.
- **Valores financeiros sempre `NUMERIC`** — nunca float. Preços `NUMERIC(38,18)` (tokens com muitas casas), quantias/capitalização `NUMERIC(38,8)`, percentuais `NUMERIC(18,8)`, câmbio `NUMERIC(24,10)`.
- Datas sempre `TIMESTAMPTZ` em UTC; a conversão para o fuso do usuário é feita na apresentação.
- Convenção de nomes de constraints fixa (`pk_`, `fk_`, `uq_`, `ck_`, `ix_`) para migrations previsíveis.
- **Isolamento por usuário**: toda tabela com dados de usuário tem `user_id NOT NULL` com FK `ON DELETE CASCADE` e índice iniciando por `user_id`.
- Migrations com **Alembic** (autogenerate revisado manualmente). CI roda `alembic upgrade head` + `alembic check` para garantir que os modelos e as migrations não divergem. Migrations destrutivas seguem *expand → migrate → contract* em deploys separados.

## Fase 1 (implementado)

| Tabela | Propósito | Destaques |
|---|---|---|
| `users` | conta | `email` único e minúsculo (check), `password_hash` argon2id, `mfa_secret_encrypted` (Fernet), `email_verified_at`, `password_changed_at` |
| `user_settings` | preferências (1:1) | `base_currency` ∈ {BRL, USD} (check), `locale`, `timezone` |
| `user_sessions` | sessões no servidor | `token_hash` único (HMAC), `expires_at`, `last_seen_at`, `revoked_at`, IP/user-agent |
| `auth_tokens` | links de e-mail de uso único | `purpose` enum (`email_verification`, `password_reset`), `token_hash` único, `expires_at`, `consumed_at` |
| `mfa_recovery_codes` | códigos de recuperação 2FA | `code_hash` único, `used_at` |
| `audit_logs` | trilha de auditoria | `user_id` com `SET NULL` (preserva trilha), `action`, `context JSONB` |
| `cryptocurrencies` | catálogo de ativos | único por (`source`, `source_id`) — símbolos **não** são únicos no mercado cripto |
| `market_tickers` | última cotação por ativo/moeda | upsert a cada sincronização; único (`cryptocurrency_id`, `quote_currency`) |
| `market_prices` | histórico intradiário de cotações | append-only, deduplicado por (`cryptocurrency_id`, `quote_currency`, `source_updated_at`); retenção 7 dias |
| `fx_rates` | câmbio (USD→BRL) | único por (`base`, `quote`, `observed_at`); `rate > 0` (check) |

## Fase 2 (implementado)

| Tabela | Propósito | Destaques |
|---|---|---|
| `portfolios` | carteiras do usuário | `user_id` FK cascade; a padrão é criada no primeiro acesso |
| `transactions` | fonte da verdade da carteira | `type` enum (buy, sell, deposit, withdrawal, transfer, fee, conversion); `quantity > 0`; `unit_price`, `gross_amount`, `fee_amount` (moeda de cotação), `fee_quantity` (unidades do ativo); `to_cryptocurrency_id`/`to_quantity` obrigatórios só em conversões (check); `fx_usd_brl` da data da operação (`> 0`); `user_id` desnormalizado para isolamento; único (`portfolio_id`, `source`, `external_id`) para deduplicação de importações |
| `exchanges` | catálogo de exchanges/carteiras | seed na migration; FK opcional nas transações (origem e destino) |
| `daily_prices` | fechamento diário em USD por ativo | único (`cryptocurrency_id`, `day`); `day` = dia UTC do fechamento |

Decisão: `portfolio_assets` (posições materializadas) e `portfolio_snapshots` **não** foram criados. Posições e séries são recalculadas a partir das transações a cada leitura — milissegundos para carteiras pessoais — o que elimina inconsistência ao editar transações antigas. Se o volume exigir, entram como cache invalidado por transação, sem mudar contratos.

## Fase 3 (implementado)

| Tabela | Propósito | Destaques |
|---|---|---|
| `historical_candles` | candles fechados (OHLCV, cotados em USDT) | único (`cryptocurrency_id`, `timeframe`, `open_time`); checks de consistência OHLC e timeframe suportado; `source`/`source_symbol` para proveniência |
| `watchlists` | listas do usuário | único (`user_id`, `name`); índice único parcial garante uma única lista padrão ("Favoritos") por usuário |
| `watchlist_assets` | ativos de cada lista | PK (`watchlist_id`, `cryptocurrency_id`) — idempotente |

`technical_indicators` não foi criada: indicadores são recalculados a cada leitura e os usados em sinais serão gravados junto ao sinal (Fase 4).

## Fase 4 (implementado)

| Tabela | Propósito | Destaques |
|---|---|---|
| `signal_strategies` | configuração versionada | único (`key`, `version`); pesos e limiares em JSONB; seed `voryn-core` v1 |
| `analysis_signals` | histórico de sinais | único (`cryptocurrency_id`, `timeframe`, `strategy_id`, `candle_time`); score 0–100 (check); componentes, indicadores, riscos e invalidação em JSONB; proveniência e qualidade dos dados |
| `alerts` | regras do usuário | `type` enum; `params` validados por tipo; `cooldown_minutes` 15–10080 (check); `last_state` para disparo por cruzamento |
| `notifications` | entregas no aplicativo | único (`user_id`, `dedupe_key`); `alert_id` SET NULL; canais usados; `read_at` |

## Fase 5 (implementado)

A entidade `ai_analysis` do projeto original virou duas tabelas: uma conversa tem várias mensagens.

| Tabela | Propósito | Destaques |
|---|---|---|
| `ai_conversations` | conversas do usuário | `user_id` CASCADE; provedor, modelo e `prompt_version` fixados na criação; `turns` |
| `ai_messages` | histórico somente de acréscimo | `role` (user, assistant, tool_results); `native` JSONB reenviado ao provedor sem alterações; texto exibido, ferramentas chamadas, fontes (com `as_of`), `stop_reason` e tokens |

## Fase 6 (implementado)

| Tabela | Propósito | Destaques |
|---|---|---|
| `backtest_runs` | execuções de backtest | `status` (queued/running/done/failed, check); estratégia, parâmetros, `optimize`; `fee_bps`/`slippage_bps` 0–100 e `train_pct` 50–90 (checks); resultado JSONB com métricas de treino/validação, curva e operações; `engine_version` |
| `exchange_connections` | chaves somente leitura | `api_key_encrypted`/`api_secret_encrypted` (Fernet); único (`user_id`, `exchange_id`, `key_fingerprint`); `permissions` validadas; `status` (active/error/blocked, check); `sync_cursor` incremental; `reconciliation` |
| `exchange_records` | registros sincronizados | único (`connection_id`, `external_id`) para deduplicar; `status` pending/imported/needs_review (check) com motivo; CASCADE da conexão |

Transações importadas usam `source` = exchange e `external_id` = id do registro; a unicidade existente (`portfolio_id`, `source`, `external_id`) impede duplicatas.

## Política de retenção

| Dado | Retenção |
|---|---|
| `market_prices` | 7 dias (configurável) |
| `historical_candles` | 15m: 60 dias · 1h: 1 ano · 4h/1d/1w: indefinida (base para backtests) |
| `fx_rates` | 1 ano (observações PTAX e ao vivo) |
| `daily_prices` | indefinida (valuation histórica) |
| sessões/tokens expirados | 30 dias após expiração |
| `notifications` | lidas: 90 dias · todas: 180 dias |
| `analysis_signals` | indefinida (auditoria e backtest de sinais) |
| `audit_logs` | indefinida até definição da política LGPD |
