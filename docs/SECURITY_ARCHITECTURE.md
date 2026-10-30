# Arquitetura de segurança

Como a Voryn protege contas, dados financeiros, credenciais de exchange e a confiabilidade das recomendações. Os detalhes de cada controle de autenticação e os limites de requisição estão em [SECURITY.md](SECURITY.md). As auditorias e o que mudou estão em [SECURITY_AUDIT.md](../SECURITY_AUDIT.md) e [SECURITY_IMPLEMENTATION_REPORT.md](SECURITY_IMPLEMENTATION_REPORT.md).

## Visão geral

```
navegador ──HTTPS──▶ borda Railway ──▶ web (Next.js + BFF) ──rede privada──▶ api (FastAPI)
                    sobrescreve                │                              │
                    X-Real-IP                  │                   ┌──────────┼──────────┐
                                     descarta cabeçalhos       Postgres    Redis     worker/beat
                                     de IP do cliente e        (dados,     (limites,  (Celery: mercado,
                                     escreve X-Forwarded-For   auditoria)  eventos)   sinais, exchanges,
                                                                                      e-mails, alertas)
```

| Fronteira | Garantia |
|---|---|
| Internet → `web` | HTTPS (HSTS), CSP, `X-Frame-Options: DENY`. Única porta pública. |
| `web` → `api` | Rede privada do Railway. A `api` não tem domínio público. O BFF repassa cookies e o CSRF, e define o IP do cliente. |
| `api` → Postgres/Redis | Rede privada; credenciais em variáveis de referência do Railway. |
| `api`/`worker` → provedores | Só HTTPS para endereços fixos da configuração (CoinGecko, Binance, BCB, Resend, Anthropic). Nenhuma URL vem do usuário, então não há SSRF. Em produção a API recusa iniciar se um endereço de provedor não for `https://`. |

## Autenticação e autorização

**Autenticação** (detalhes em [SECURITY.md](SECURITY.md#autenticação)):
- **Senha:** argon2id.
- **Sessão:** token opaco de 256 bits em cookie `HttpOnly; Secure; SameSite=Lax`; no banco fica só o HMAC.
- **CSRF:** double-submit.
- **2FA:** TOTP com proteção contra reutilização do código e limite de 10 falhas por hora por conta. Ativar exige a senha; desativar exige senha e segundo fator.

**Autorização por recurso.** Não existe papel de administrador: toda função age sobre os dados do próprio usuário.
- **A identidade vem só da sessão.** Nenhuma rota aceita `user_id` do cliente. Um `user_id` enviado no corpo é ignorado, porque os schemas são explícitos (teste `test_owner_cannot_be_reassigned_through_the_request_body`).
- **Toda rota que carrega um recurso por ID usa `app/core/authz.owned_or_404`.** O recurso de outra pessoa responde `404` idêntico ao de um ID inexistente, para que IDs não possam ser sondados. A tentativa fica registrada na auditoria (`authz.access_denied`) e no monitoramento.
- **Listas e agregados** (carteira, transações, notificações, sessões) filtram por `user_id` da sessão na própria consulta.
- **Autenticação obrigatória:** `tests/test_authorization.py` percorre a tabela de rotas e exige `401` sem sessão em todas, exceto 8 rotas públicas de cadastro, login e recuperação.

### Isolamento financeiro e Row Level Security

Avaliamos o RLS do PostgreSQL e **não o adotamos agora**. Motivos:
1. A aplicação usa um único usuário de banco, dono das tabelas. O RLS não se aplica ao dono, a menos que se use `FORCE ROW LEVEL SECURITY`, e isso exigiria passar o usuário corrente para o banco em cada transação (`SET LOCAL`), inclusive nas tarefas do worker que agem sobre todos os usuários.
2. O isolamento já é imposto em um único ponto (`owned_or_404` e os filtros por sessão) e é verificado por testes com dois usuários em cada módulo.

**Quando adotar:** ao separar o usuário de banco da aplicação (sem privilégio de DDL) do usuário de migração. É o passo P2 em [Riscos residuais](#riscos-residuais).

## Proteção de credenciais

| Segredo | Onde fica | Proteção |
|---|---|---|
| Senha | `users.password_hash` | argon2id; nunca registrada em log, auditoria ou relatório de erro |
| Token de sessão e links de e-mail | só HMAC-SHA256 no banco (`SECRET_KEY`) | um vazamento do banco não permite sequestrar sessões |
| Chave e segredo de exchange, segredo TOTP | cifrados com Fernet (AES-128-CBC + HMAC-SHA256, criptografia autenticada) | a chave (`ENCRYPTION_KEYS`) fica em variável do Railway, separada do banco; `SecretStr` desde a entrada, para não aparecer em `repr`, logs ou Sentry |
| Chaves de serviço (Resend, Anthropic…) | variáveis do Railway | nunca versionadas; Gitleaks no CI |

**Rotação da chave de criptografia:**
1. Gere uma chave nova (`scripts/generate_secrets.py`) e defina `ENCRYPTION_KEYS="nova,antiga"`. A nova cifra; as duas decifram.
2. No serviço `api`, rode `python -m app.core.key_rotation`. Ele recifra credenciais de exchange e segredos TOTP; o texto em claro nunca sai da chamada `rotate`.
3. Com `failed=0`, defina `ENCRYPTION_KEYS="nova"` e destrua a antiga.

**Rotação da chave de API da exchange:** desconecte e conecte a chave nova. As transações importadas permanecem e não são duplicadas, porque são identificadas pelo ID externo da exchange.

## Integrações com exchanges

`app/modules/exchange_connections/connectors/` é a camada única de integração. A interface `ExchangeConnector` tem só três métodos de **leitura**: `permissions`, `balances` e `history`. **Não existe código de envio de ordens ou de saque.**

| Controle | Implementação |
|---|---|
| Menor privilégio | Só chaves somente leitura. Qualquer outra permissão, inclusive uma desconhecida, recusa a conexão. A restrição por IP (`ipRestrict`) é aceita. A permissão é verificada de novo a cada sincronização; se a chave ganhar escrita, a conexão é bloqueada. |
| Revogação | "Desconectar" apaga as credenciais e os registros sincronizados. Uma chave revogada na exchange bloqueia a conexão na próxima sincronização. |
| Timeouts e retry | 20 s por chamada. Falhas de rede e 5xx: até 2 novas tentativas com espera exponencial (1 s, 2 s). 418/429 não são repetidos, porque a Binance bane quem insiste. |
| Validação de respostas | Payload em formato inesperado vira `ConnectorError` genérico; nada parcial é gravado. |
| Isolamento de falhas | Cada conexão sincroniza e falha sozinha (estado, auditoria `exchange.sync_failed`/`exchange.blocked`, evento de monitoramento). A falha de uma conta não afeta as outras. |
| Limites | 5 conexões por hora por usuário; sincronização manual a cada 2 min no mínimo; sincronização automática a cada 6 h. |
| Exibição | Nome da exchange, status, últimos 4 caracteres da chave, permissões, última sincronização, erro e "Desconectar". As credenciais nunca voltam ao navegador. |

## Integridade das recomendações

Os sinais são **regras transparentes** ([SIGNALS.md](SIGNALS.md)). Antes de classificar, `app/modules/signals/quality.py` avalia os dados:

| Status | Quando | Efeito |
|---|---|---|
| `valid` | candles recentes, completos e coerentes | classificação normal |
| `stale` | a fonte não atualizou a tempo (a janela depende do timeframe), ou a análise tem mais de 3 candles | compra e venda suspensas; marcado como "histórico" se não for atual |
| `incomplete` | menos de 60 candles fechados, ou indicadores essenciais sem dados | compra e venda suspensas |
| `anomalous` | volume zero; variação de mais de 50% em um candle; preço divergente da cotação CoinGecko (10% a 40%, conforme o timeframe) | compra e venda suspensas |
| `unavailable` | a fonte falhou e só existe uma análise antiga | a última análise aparece como **histórica**, nunca como atual |

Além disso, os candles da Binance passam por verificação de consistência (OHLC coerente, valores positivos e finitos). Na primeira associação de um par, um desvio acima de 5% em relação à cotação recusa o par.

**Rastreabilidade:** cada sinal guarda ativo, timeframe, horário do candle de referência, horário de geração, preço de referência, fonte e par, horário dos dados, indicadores, componentes do score, estratégia e versão, versão da metodologia, status de qualidade e motivos. Um sinal é único por candle, estratégia e versão: gerar de novo não altera o registro.

**Bloqueio e reprocessamento:**
- O bloqueio gera o evento `signal_blocked`, com a causa.
- As análises anteriores continuam no histórico.
- A geração roda a cada 30 min e também a cada consulta de ativo, então um dado normalizado produz um sinal novo sozinho.
- O Voryn AI recebe `data_quality`, `is_current` e, quando o sinal é histórico, a instrução de não apresentá-lo como recomendação atual.

**Proteção contra manipulação:** scores, pesos e estratégias não têm rota de escrita. O único parâmetro de consulta é o timeframe, que é validado (teste `test_recommendations_cannot_be_steered_by_the_client`).

## Pipeline DevSecOps

`.github/workflows/security.yml` roda em todo pull request e em todo push na `main`.

| Etapa | Ferramenta | Bloqueia quando |
|---|---|---|
| 1. Segredos | Gitleaks (histórico completo, `--redact`) | qualquer segredo novo; falsos positivos conhecidos ficam em `.gitleaksignore`, com o motivo |
| 2. Dependências | pip-audit `--strict` (dependências Python travadas, inclusive transitivas); npm audit (dependências de execução) | Python: qualquer vulnerabilidade conhecida; Node: alta ou crítica |
| 3. SAST | Semgrep: Python, FastAPI, TypeScript, React, Next.js, Dockerfile, segredos, OWASP Top 10 | qualquer achado; exceções com `nosemgrep` e justificativa no próprio código |
| 4. Contêineres | Trivy nas duas imagens de produção e nos Dockerfiles; checagem de usuário sem privilégios | vulnerabilidade alta ou crítica com correção disponível; má configuração alta; imagem rodando como root |
| 5–6. Testes e build | `ci.yml` (reutilizável): lint, tipos, migrations (sobe, desce, sobe e confere com os modelos), testes de autorização e segurança, suíte completa, build do frontend | qualquer falha |

**Endurecimento do próprio pipeline:**
- **Permissões:** `GITHUB_TOKEN` só com `contents: read`, e o `checkout` sem credenciais persistidas.
- **Pull requests de forks:** o gatilho é `pull_request` (não `pull_request_target`), então código de fork roda sem segredos. Nenhuma etapa usa segredos.
- **Versões fixadas:** actions por SHA de commit e imagens das ferramentas por digest.
- **Cache:** só de dependências, com chave pelo lockfile.
- **Deploy:** não há deploy no pipeline; o Railway implanta a `main` sozinho.
- **Cadeia de suprimentos Python:** o `uv` só resolve versões publicadas há mais de 7 dias (`exclude-newer`).

**Para impedir merge com falha** (configuração no GitHub, uma vez): Settings → Branches → Add rule para `main`:
1. Marque "Require a pull request before merging".
2. Marque "Require status checks to pass" e selecione `Secret scanning (gitleaks)`, `Dependency scanning (pip-audit, npm audit)`, `Static analysis (semgrep)`, `Container scanning (trivy)`, `Tests and build / Backend tests` e `Tests and build / Frontend tests and build`.
3. Marque "Do not allow bypassing the above settings".

## Monitoramento e auditoria

**Eventos de segurança** (`app/core/security_events.py`): cada evento gera uma linha `security_event` nos logs do Railway e incrementa um contador no Redis por janela de 5 min. A tarefa `security.check` (a cada 5 min) compara a janela anterior com os limites abaixo e emite `security_alert`: log de erro e, se `SECURITY_ALERT_EMAIL` estiver definida, um e-mail. Cada tipo alerta no máximo uma vez por hora.

| Evento | Limite por 5 min |
|---|---|
| `login_failed` | 50 |
| `mfa_failed` | 10 |
| `session_invalid` | 200 |
| `access_denied` | 10 |
| `rate_limited` | 100 |
| `exchange_sync_failed` | 20 |
| `signal_blocked` | 50 |
| `processing_failed` (backtests) | 10 |
| `server_error` (500) | 10 |

Para investigar, filtre os logs do Railway por `security_event`, `security_alert` ou pelo `request_id` de uma resposta.

**Auditoria** (`audit_logs`):
- **Conteúdo:** usuário, ação, IP, user-agent, `request_id` e contexto **sem** senhas, tokens ou segredos (testado).
- **Integridade:** somente inserção, garantida por gatilho no banco.
- **Retenção:** 365 dias, com limpeza diária.
- **Acesso:** sem rota de leitura na API.

O gatilho protege contra erros da aplicação e injeção de SQL, não contra quem administra o banco.

## Riscos residuais

| Prioridade | Risco | Mitigação atual / próximo passo |
|---|---|---|
| P1 | Chave do Resend exposta em conversa durante o deploy | trocar no Resend e na variável compartilhada |
| P1 | Backups do Postgres não verificados | ativar backups do volume no Railway e testar restauração |
| P2 | Um único usuário de banco, dono das tabelas (pode desligar o gatilho de auditoria; impede RLS efetivo) | separar usuário da aplicação (sem DDL) do usuário de migração; então avaliar RLS |
| P2 | Proteção da `main` depende de configuração manual no GitHub | aplicar as regras acima |
| P2 | Bloqueio direcionado: terceiros podem travar o login de uma conta por 15 min ou o 2FA por 1 h | intencional (temporário); monitorado por `login_failed`/`mfa_failed` |
| P3 | CSP com `script-src 'unsafe-inline'` (scripts de inicialização do Next.js) | nonce exige renderização dinâmica de todas as páginas |
| P3 | Voryn AI não testado ao vivo contra prompt injection (sem chave configurada) | ferramentas somente leitura e presas à sessão; testar ao ativar |
| P3 | Limites de alerta calibrados para o tráfego atual | revisar com o crescimento |
| P3 | Retenção e exportação de dados pessoais (LGPD) não formalizadas | definir com os termos de uso |
