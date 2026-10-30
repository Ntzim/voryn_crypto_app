# Relatório de implementação — evolução de segurança

**Data:** 30/10/2026 · **Branch:** `security/evolution` (8 commits, 46 arquivos; **não implantada**) · **Base:** `main` em `d816402`, que já inclui as correções de [SECURITY_AUDIT.md](../SECURITY_AUDIT.md) e o 2FA com senha.

A arquitetura resultante está em [SECURITY_ARCHITECTURE.md](SECURITY_ARCHITECTURE.md). Este relatório registra o que mudou, como foi testado e o que falta.

## O que já existia e foi mantido

Antes de implementar, cada item da missão foi comparado com o código. Já estavam corretos e foram só verificados:
- Isolamento por `user_id` da sessão em todas as consultas, com testes de dois usuários por módulo.
- Credenciais de exchange cifradas com Fernet (criptografia autenticada), chave fora do banco, nunca devolvidas ao navegador, só chaves de leitura.
- Rastreabilidade dos sinais: fonte, horários, indicadores, versões de estratégia e metodologia.
- Rate limit em login, cadastro, recuperação de senha, IA, backtests e conexões.
- Auditoria de autenticação.
- Logs estruturados (structlog, JSON).

## Melhorias implementadas

| Sprint | Melhoria | Commit |
|---|---|---|
| 1 — Proteção de dados | Autorização por recurso centralizada (`owned_or_404`) em carteiras, transações, alertas, watchlists, backtests, conversas da IA e conexões; acesso a recurso alheio auditado e contado, com resposta idêntica a "não encontrado" | `3b9c624` |
| 2 — Exchanges | Retry com espera exponencial só para falhas transitórias; validação de respostas da Binance; falhas e bloqueios auditados por conexão; endereços de provedores obrigatoriamente HTTPS em produção; comando de rotação da chave de criptografia; tela de integrações mostra as permissões | `e054e01`, `3b9c624`, `07da7eb`, `7c6df92` |
| 3 — Recomendações | Qualidade de dados em 5 estados, com motivos, gravada em cada sinal; dados incompletos ou anômalos suspendem compra e venda; sinais antigos marcados como históricos na API, na tela e no Voryn AI | `fd4b139` |
| 4 — DevSecOps | `security.yml` com Gitleaks, pip-audit, npm audit, Semgrep (com OWASP Top 10), Trivy (imagens e Dockerfiles), checagem de usuário sem privilégios, e testes e build via `ci.yml` reutilizável; actions por SHA, imagens por digest; quarentena de 7 dias para versões novas de pacotes Python; imagem da API sem pip | `08bd8b5`, `a869a32`, `dd109ce` |
| 5 — Observabilidade | Auditoria somente inserção (gatilho no banco), com `request_id`, retenção de 365 dias e novos eventos; eventos de segurança com contadores e alertas por e-mail (`SECURITY_ALERT_EMAIL`); limites por usuário em escrita de transações, importação CSV, desempenho, análise, sinal por ativo e risco; aviso de `429` no frontend | `3b9c624`, `7c6df92` |

## Vulnerabilidades e falhas corrigidas

| ID | Severidade | Problema | Correção | Teste |
|---|---|---|---|---|
| E-01 | Média | Com o provedor de candles fora do ar, `GET /signals/{ativo}` devolvia o último sinal salvo, que podia ter semanas, marcado como atual; o Voryn AI repassava esse sinal como atual | qualidade avaliada também no momento da leitura; `is_current=false` e status `stale`/`unavailable`; aviso na tela e no Voryn AI | `test_signals_are_never_shown_as_current_when_data_is_not` |
| E-02 | Média | Com menos de 60 candles a tendência fica "indefinida", e o motor ainda podia classificar como "potencial de compra" | dados incompletos suspendem compra e venda | `test_short_history_suspends_the_signal` |
| E-03 | Alta (imagem) | A imagem da API trazia o pip com `urllib3`, `msgpack` e `setuptools` vulneráveis embutidos (5 achados HIGH no Trivy) | pip removido da imagem final; 0 achados | Trivy local, código de saída 0 |
| E-04 | Média | Cadeia de suprimentos: o `uv` resolvia versões publicadas minutos antes (achado do Semgrep) | `exclude-newer = "7 days"`, sem mudar nenhuma versão travada | Semgrep, código de saída 0 |
| E-05 | Baixa | Resposta malformada da Binance gerava exceção não tratada na sincronização | `ConnectorError` genérico, sem o conteúdo bruto | `test_malformed_exchange_payloads_fail_cleanly` |
| E-06 | Baixa | Dados cifrados nunca podiam sair da chave antiga | `python -m app.core.key_rotation` | `test_encryption_key_rotation_lets_the_old_key_be_retired` |

## Testes executados

Todos foram executados nesta máquina, com Postgres 17 real (Docker) e a pilha completa local para os testes de navegador.

| Teste | Resultado |
|---|---|
| Backend: pytest (unitários, integração, financeiros, autorização, segurança) | **209 aprovados** (eram 181 antes desta etapa) |
| Backend: ruff, mypy, `alembic upgrade → downgrade → upgrade → check` nas duas migrations novas | sem problemas |
| Frontend: Vitest / ESLint / `tsc` / `next build` | 28 aprovados / sem problemas |
| E2E Playwright (navegador real): 2FA (desktop e celular), oportunidades, análise, exchanges, carteira, risco | 11 aprovados |
| Gatilho de auditoria no banco migrado (`UPDATE`/`DELETE` manuais) | recusados |
| Pipeline, local e com as mesmas imagens fixadas: Gitleaks, pip-audit `--strict`, npm audit `high`, Semgrep (OWASP incluído), Trivy imagens e Dockerfiles, usuário das imagens, actionlint | todos com código de saída 0 |

**Cenários obrigatórios da missão:**

| Cenário | Teste |
|---|---|
| 1. Isolamento financeiro: A não vê, altera nem exclui recursos de B, nem por manipulação de IDs | `test_portfolios_are_isolated` (carteira, transações por ID inclusive via a própria carteira, importação, risco), `test_*_isolation` de cada módulo e `test_reaching_another_users_resource_is_audited_but_looks_missing` |
| 2. Credenciais | `test_no_endpoint_ever_returns_exchange_credentials` (todas as rotas de exchange, banco e auditoria) |
| 3. Integrações | `test_a_failing_exchange_affects_only_its_connection`, retry, 429 e payload malformado |
| 4. Dados desatualizados | `test_signal_quality.py` (11 testes) |
| 5. Manipulação de parâmetros | `test_recommendations_cannot_be_steered_by_the_client` e `test_owner_cannot_be_reassigned_through_the_request_body` |
| 6. Rate limiting | `test_throttled_requests_answer_429_and_are_counted`, `test_costly_endpoints_are_limited_per_user_not_per_address` e os testes de login e 2FA |
| 7. Autenticação | `test_every_other_route_requires_a_session` (todas as rotas; validado por mutação) |
| 8. Auditoria | `test_security_events_are_audited_without_secrets`, append-only, anonimização, retenção e alertas |

**Não executado:** o workflow no GitHub Actions. A branch ainda não foi enviada, e a execução real depende de um pull request.

## Pendências

1. **Deploy (precisa da sua aprovação):** mesclar `security/evolution` na `main`. A API roda as duas migrations novas no pre-deploy; ambas só acrescentam (colunas com padrão e um gatilho) e foram testadas para subir e descer.
2. **Primeira execução do pipeline no GitHub:** abrir o pull request desta branch e conferir os 6 jobs.
3. **Proteção da `main`:** configurar os checks obrigatórios ([passo a passo](SECURITY_ARCHITECTURE.md#pipeline-devsecops)). Requer acesso de administrador ao repositório.
4. **`SECURITY_ALERT_EMAIL`:** definir no serviço `worker` para receber alertas por e-mail.
5. **Chave do Resend:** gerar uma nova e trocar a variável compartilhada (exposta em conversa).
6. **Backups do Postgres:** ativar e testar restauração.

## Próximos passos

**P1:** itens 1 a 6 acima.

**P2:**
- Separar o usuário de banco da aplicação (sem DDL) do de migração; depois avaliar RLS.
- Prefixo `__Host-` nos cookies.
- Alerta de login em novo dispositivo.

**P3:**
- CSP com nonce.
- Teste ao vivo de prompt injection quando o Voryn AI for ativado.
- Revisar limites de alerta com o crescimento do tráfego.
- Política de retenção e exportação de dados (LGPD).
- Remover as exceções de quarentena do `pyproject.toml` depois de 04/11/2026.
