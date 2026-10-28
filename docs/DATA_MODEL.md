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

## Fases seguintes (projeto)

| Tabela | Fase | Chaves e constraints planejadas |
|---|---|---|
| `portfolios` | 2 | `user_id` FK; um usuário pode ter várias carteiras; `base_currency` |
| `transactions` | 2 | `portfolio_id` FK, `type` enum (buy, sell, deposit, withdrawal, transfer_in, transfer_out, fee, conversion), `cryptocurrency_id`, `quantity NUMERIC(38,18) > 0`, `unit_price`, `quote_currency`, `fee_amount`, `fee_currency`, `executed_at`, `exchange_id`, `external_id` (único por conexão, para deduplicação de sync), `transfer_group_id` (liga as pernas de uma transferência interna para não contar como aporte/lucro), `notes` |
| `portfolio_assets` | 2 | posição materializada por (`portfolio_id`, `cryptocurrency_id`): quantidade, custo total, preço médio, resultado realizado — recalculável a partir de `transactions` (fonte da verdade) |
| `portfolio_snapshots` | 2 | (`portfolio_id`, `as_of`) único; valor de mercado, fluxos externos do período — base para TWR/XIRR e gráficos |
| `exchanges` | 2 | catálogo (Binance, Coinbase, Kraken, manual, CSV) |
| `exchange_connections` | 6 | `user_id`, `exchange_id`, `api_key_encrypted`, `api_secret_encrypted`, `permissions` (validado: somente leitura), `last_synced_cursor` |
| `historical_candles` | 3 | (`cryptocurrency_id`, `timeframe`, `open_time`) único; OHLCV em NUMERIC; candidata a particionamento por mês ou TimescaleDB |
| `technical_indicators` | 3 | cache de indicadores por (`cryptocurrency_id`, `timeframe`, `indicator`, `params_hash`, `open_time`) |
| `watchlists`, `watchlist_assets` | 3 | `user_id` FK; único (`watchlist_id`, `cryptocurrency_id`) |
| `signal_strategies` | 4 | versão da estratégia, pesos (JSONB validado), `is_active` |
| `analysis_signals` | 4 | ativo, timeframe, `strategy_version`, preço de referência, score 0–100 (check), classificação, indicadores usados (JSONB), justificativa, condições de invalidação, `data_fetched_at`, `data_is_stale` |
| `alerts` | 4 | `user_id`, tipo, condição (JSONB validado), `cooldown_seconds`, `last_triggered_at` |
| `notifications` | 4 | `user_id`, canal, `dedupe_key` único por usuário/janela, `read_at` |
| `ai_analysis` | 5 | `user_id`, intenção, contexto estruturado enviado ao modelo, resposta, provedor/modelo, tokens, `data_as_of` |
| `backtest_runs` | 6 | `user_id`, estratégia/versão, período de treino e validação, custos/slippage, métricas, resultado |

## Política de retenção

| Dado | Retenção |
|---|---|
| `market_prices` | 7 dias (configurável) |
| `historical_candles` | indefinida (base para backtests) |
| `fx_rates` | 1 ano |
| sessões/tokens expirados | 30 dias após expiração |
| `notifications` lidas | 90 dias (planejado) |
| `audit_logs` | indefinida até definição da política LGPD |
