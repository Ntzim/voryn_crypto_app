# Plano de implementação

Cada fase termina com: testes automatizados verdes, zero erros de tipos (mypy strict / tsc), fluxos principais validados em desktop e mobile, revisão de segurança, documentação atualizada e limitações registradas. Nenhuma fase começa com erros críticos na anterior.

## Fase 1 — Fundação ✅

- [x] Monorepo `backend/` + `frontend/`, Docker Compose, Dockerfiles prontos para Railway
- [x] PostgreSQL + Alembic (migration inicial, `alembic check` no CI)
- [x] Autenticação: cadastro, verificação de e-mail, login, logout, recuperação de senha, 2FA TOTP + códigos de recuperação, gerenciamento de sessões, troca de senha
- [x] Proteções: rate limiting (IP e conta), CSRF, anti-enumeração, auditoria, security headers
- [x] Perfil e preferências (moeda base, idioma, fuso)
- [x] Integração de mercado: CoinGecko (top 100 + USD/BRL), validação, retry/backoff, indicador de dados desatualizados
- [x] Design system Voryn (tokens, tipografia Sora/Inter, componentes shadcn/ui tematizados)
- [x] Layout principal: sidebar, trilho para tablet, navegação inferior mobile
- [x] Dashboard de mercado (dados reais), listagem de mercado com busca/ordenação, página do ativo (visão geral)
- [x] CI: lint, tipos, testes, build

## Fase 2 — Carteira funcional ✅

- [x] Modelos `portfolios`, `transactions`, `exchanges` (seed), `daily_prices` + migration
- [x] Motor de posição puro: custo médio ponderado, realizado/não realizado, taxas (em moeda e no ativo), transferências internas, conversões — testado com exemplos calculados à mão
- [x] Cotação USD/BRL histórica oficial (PTAX/BCB) gravada por transação → resultado exato em BRL e USD
- [x] CRUD de transações com validação do histórico completo (sem saldo negativo, inclusive ao editar/excluir)
- [x] Importação CSV (modelo Voryn) com pré-visualização, erros por linha e deduplicação
- [x] Rentabilidade: TWR (24h/7d/30d/90d/1a/início), XIRR (desde o início), variação 24h separando mercado de aportes
- [x] Dashboard patrimonial: BRL/USD, resultado, gráfico de evolução com aportes/retiradas e comparação BTC/ETH (Lightweight Charts), distribuição (Recharts), principais posições
- [x] Insights determinísticos com metodologia explícita (concentração, stablecoins, movimento 24h, posições abaixo do preço médio, correlação)
- [x] Jobs: sincronização dos ativos em carteira fora do top 100, backfill de fechamentos diários e PTAX
- [x] Metodologia documentada em [PORTFOLIO.md](PORTFOLIO.md)

Pendências registradas: mapeadores de extrato Binance/Coinbase, cadastro de ativos fora do catálogo (busca na CoinGecko), histórico de preços > 365 dias (plano pago), múltiplas carteiras na interface (a API já suporta).

## Fase 3 — Inteligência de mercado

Candles (15m/1h/4h/1d/1w) com provedor apropriado e cache, motor de indicadores determinístico (RSI, MACD, EMA 9/21/50/200, SMA, Bollinger, ATR, volume, suporte/resistência documentado) com testes contra valores de referência, classificação de tendência justificada, gráfico de candles, watchlists/favoritos.

## Fase 4 — Oportunidades

Motor de sinais versionado (pesos configuráveis), score 0–100 (não é probabilidade), classificação, justificativa e condições de invalidação, bloqueio/aviso quando dados estão desatualizados, histórico de sinais, alertas (preço, RSI, cruzamentos, volume, tendência, score, concentração) com deduplicação, cooldown, notificações in-app e e-mail.

## Fase 5 — Voryn AI

Camada `LLMProvider` intercambiável, roteamento de intenção, ferramentas que consultam apenas os motores internos, respostas que separam dados observados / interpretação / hipóteses / riscos, com período e horário dos dados. Sem execução de ordens.

## Fase 6 — Recursos avançados

Conectores de exchange somente leitura (Binance, Coinbase, Kraken) com sync incremental, deduplicação e reconciliação; análise de risco (volatilidade, drawdown, correlação, VaR histórico, concentração, stablecoins, liquidez) e simulador de cenários; backtesting sem look-ahead, com custos/slippage e separação treino/validação; otimizações de performance.
