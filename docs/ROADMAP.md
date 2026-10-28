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

## Fase 2 — Carteira funcional

1. Modelos `portfolios`, `transactions`, `portfolio_assets`, `portfolio_snapshots`, `exchanges` + migration.
2. Motor de posição (puro, sem I/O): custo médio ponderado, resultado realizado/não realizado, taxas, transferências internas (`transfer_group_id`) e conversões (venda + compra atômicas). Testes com casos conhecidos (planilhas de referência).
3. CRUD de transações com validação (não permitir vender mais do que possui na data).
4. Importação CSV: template próprio + mapeadores para extratos Binance/Coinbase; pré-visualização, deduplicação por hash de linha, relatório de erros por linha.
5. Snapshots diários (job) e cálculo de rentabilidade: TWR (períodos 24h/7d/30d/90d/1a/início) e XIRR (desde o início), separando efeito de mercado de aportes/retiradas.
6. Dashboard patrimonial: patrimônio BRL/USD, resultado, variação 24h, gráfico de evolução (Lightweight Charts) com aportes/retiradas e comparação BTC/ETH, distribuição (Recharts), tabela de posições.
7. Insights rápidos determinísticos (concentração, maior variação, etc.) com o cálculo exibido.

## Fase 3 — Inteligência de mercado

Candles (15m/1h/4h/1d/1w) com provedor apropriado e cache, motor de indicadores determinístico (RSI, MACD, EMA 9/21/50/200, SMA, Bollinger, ATR, volume, suporte/resistência documentado) com testes contra valores de referência, classificação de tendência justificada, gráfico de candles, watchlists/favoritos.

## Fase 4 — Oportunidades

Motor de sinais versionado (pesos configuráveis), score 0–100 (não é probabilidade), classificação, justificativa e condições de invalidação, bloqueio/aviso quando dados estão desatualizados, histórico de sinais, alertas (preço, RSI, cruzamentos, volume, tendência, score, concentração) com deduplicação, cooldown, notificações in-app e e-mail.

## Fase 5 — Voryn AI

Camada `LLMProvider` intercambiável, roteamento de intenção, ferramentas que consultam apenas os motores internos, respostas que separam dados observados / interpretação / hipóteses / riscos, com período e horário dos dados. Sem execução de ordens.

## Fase 6 — Recursos avançados

Conectores de exchange somente leitura (Binance, Coinbase, Kraken) com sync incremental, deduplicação e reconciliação; análise de risco (volatilidade, drawdown, correlação, VaR histórico, concentração, stablecoins, liquidez) e simulador de cenários; backtesting sem look-ahead, com custos/slippage e separação treino/validação; otimizações de performance.
