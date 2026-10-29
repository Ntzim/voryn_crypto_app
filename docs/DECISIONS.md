# Registro de decisões técnicas (ADR resumido)

### ADR-001 — Monólito modular
**Decisão:** um backend FastAPI com módulos de domínio (`app/modules/*`) e um worker Celery do mesmo código.
**Motivo:** time pequeno, domínio ainda em descoberta; microsserviços adicionariam rede, deploy e consistência distribuída sem ganho mensurável. Fronteiras de módulo permitem extração futura.

### ADR-002 — Sessões opacas no servidor em vez de JWT
**Decisão:** token aleatório em cookie `HttpOnly`, HMAC no banco, consulta por requisição.
**Motivo:** revogação imediata (logout, troca de senha, "encerrar outras sessões"), listagem de dispositivos, sem segredo de assinatura exposto a riscos de algoritmo. O custo (1 consulta indexada por requisição) é irrelevante nesta escala e pode ganhar cache em Redis se necessário.

### ADR-003 — BFF no Next.js via route handler (não `rewrites`)
**Decisão:** `src/app/api/[...path]/route.ts` repassa as chamadas à API lendo `API_INTERNAL_URL` em tempo de execução.
**Motivo:** cookies first-party e sem CORS; `rewrites` são resolvidos no build, o que impediria usar a mesma imagem em ambientes diferentes.

### ADR-004 — Cotações em USD como fonte única; BRL derivado
**Decisão:** ingerir mercado só em USD e converter com `fx_rates` armazenado.
**Motivo:** metade das chamadas ao provedor (cota limitada), consistência entre telas, e transparência (a resposta informa a taxa e o horário usados). Limitação documentada: variações percentuais são em base USD.

### ADR-005 — CoinGecko como provedor inicial, atrás de `MarketDataProvider`
**Decisão:** CoinGecko (API pública/Demo) para catálogo e cotações.
**Motivo:** cobertura ampla, ATH/supply/market cap no mesmo endpoint, plano gratuito para desenvolvimento. Para produção comercial, avaliar plano pago (licença de redistribuição) ou combinação com feeds de exchange para candles intradiários (Fase 3).

### ADR-006 — Celery + Redis para jobs
**Decisão:** Celery (broker Redis), `beat` para agendamento; tarefas são wrappers síncronos de serviços async com engine `NullPool` por execução.
**Motivo:** maduro, retries/backoff nativos, amplamente suportado no Railway. Alternativas async (arq) têm manutenção limitada.

### ADR-007 — Decimal ponta a ponta
**Decisão:** `NUMERIC` no banco, `Decimal` no Python (inclusive parsing JSON do provedor com `parse_float=Decimal`), strings no JSON da API.
**Motivo:** evitar erros de arredondamento em valores financeiros; o frontend só formata.

### ADR-008 — Tipos do frontend gerados do OpenAPI
**Decisão:** `openapi-typescript` gera `schema.d.ts` a partir de `backend` (`npm run gen:api`).
**Motivo:** contratos únicos; mudanças quebradas no backend aparecem como erro de compilação no frontend.

### ADR-010 — Candles da Binance (dados públicos) com verificação de preço
**Decisão:** candles de `data-api.binance.vision` para o par `ATIVO/USDT`, aceitos só quando o último fechamento está a ≤ 5% do preço da CoinGecko.
**Motivo:** o plano gratuito da CoinGecko não oferece candles nos intervalos exigidos (15m–1w); a Binance tem a maior cobertura de pares, sem chave e sem bloqueio geográfico nesse host. A verificação de preço protege contra símbolos repetidos entre tokens diferentes. O provedor fica atrás de `CandleProvider`, permitindo trocar ou somar fontes.

### ADR-011 — Sinais imutáveis por candle e alertas por cruzamento
**Decisão:** um sinal por (ativo, intervalo, versão da estratégia, candle fechado); alertas disparam na transição falso→verdadeiro, com cooldown e chave de deduplicação única.
**Motivo:** auditabilidade (o histórico mostra o que a estratégia dizia, sem repintura) e notificações úteis — sem repetição enquanto a condição persiste, sem duplicatas sob concorrência.

### ADR-009 — Indicadores e sinais determinísticos; IA apenas interpreta
**Decisão (para Fases 3–5):** indicadores, scores e métricas de risco são calculados por código testado; o LLM recebe resultados estruturados e nunca gera números.
**Motivo:** auditabilidade, reprodutibilidade e o princípio do produto de não apresentar previsões como certezas.
