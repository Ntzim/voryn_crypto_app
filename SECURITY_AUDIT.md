# Auditoria de segurança — Voryn

**Data:** 30/10/2026 · **Escopo:** repositório completo (backend FastAPI, frontend Next.js/BFF, worker Celery, infraestrutura Railway, CI) e o ambiente de produção `web-production-b42218.up.railway.app`, testado apenas com leituras e tentativas de login com contas fictícias. · **Branch das correções:** `security/hardening` (ainda não implantada).

## Resumo executivo

A base de segurança da Voryn é sólida. Os controles centrais foram verificados no código e se mostraram corretos:

- **Senhas:** argon2id.
- **Sessões:** tokens opacos guardados só como HMAC, em cookie `HttpOnly; Secure; SameSite=Lax`.
- **CSRF:** double-submit, aplicado também ao login.
- **2FA:** TOTP com proteção contra reutilização do código.
- **Isolamento entre usuários:** filtro por `user_id` da sessão em todas as consultas.
- **Exchanges:** chaves cifradas com Fernet, aceitas somente se forem de leitura e nunca devolvidas ao navegador.
- **IA:** ferramentas somente leitura, presas ao usuário da sessão.
- **Configuração:** a aplicação recusa iniciar em produção com configuração insegura.

A auditoria encontrou **9 problemas**:

- **2 de prioridade alta (P1).** O mais grave foi confirmado em produção: **o limite de requisições por IP podia ser burlado** forjando o cabeçalho `X-Forwarded-For`. Isso anulava a proteção contra força bruta de senha, credential stuffing e envio massivo de e-mails. Combinado com a segunda falha (**tentativas ilimitadas de código 2FA** para quem já tem a senha), o segundo fator podia ser vencido por força bruta.
- **3 de prioridade média (P2):** open redirect após o login, vazamento latente de segredos para o Sentry e injeção de conteúdo nos e-mails enviados.
- **4 de prioridade baixa (P3):** endurecimento.

Nenhuma falha de autorização (IDOR/BOLA) foi encontrada: todas as rotas que recebem um identificador foram testadas com uma segunda conta. Não foram encontrados segredos no histórico do Git nem vulnerabilidades conhecidas nas dependências Python. As dependências npm têm só 3 alertas de severidade baixa, em ferramenta de build.

**Todas as 9 falhas foram corrigidas na branch `security/hardening`** e cobertas por testes de regressão. Para as P1 e P2, verifiquei que os testes falham no código antigo. A correção V-01 foi validada em produção depois do deploy.

**Nível de confiança:** alto para autenticação, autorização e manuseio de credenciais (revisão linha a linha mais testes automatizados); médio para a infraestrutura do Railway, que só pode ser observada de fora; baixo para o Voryn AI em execução, que não pôde ser testado ao vivo porque não há `ANTHROPIC_API_KEY` configurada. A revisão do Voryn AI foi feita só sobre o desenho. O sistema **não** deve ser considerado 100% seguro.

## Mapa da superfície de ataque

| Camada | Componentes | Exposição |
|---|---|---|
| Borda | Railway edge (HTTPS) → serviço `web` | Pública |
| BFF | Next.js 16, `src/app/api/[...path]/route.ts` repassa `/api/v1/*` | Pública |
| API | FastAPI, 70+ rotas em 14 módulos; middlewares de contexto, cabeçalhos, rate limit global e CSRF | Só rede privada |
| Worker / Beat | Celery: sincronização de mercado, sinais, alertas, e-mails, backtests, sincronização com exchanges | Sem entrada externa |
| Dados | PostgreSQL (SQLAlchemy, consultas parametrizadas) e Redis (rate limit, desafios MFA, cache) | Só rede privada |
| Integrações | CoinGecko, Binance (dados públicos e conta assinada com chave do usuário), BCB PTAX, Resend, Anthropic | Saída HTTPS |
| Rotas públicas | `auth/csrf`, `register`, `email/verify`, `email/resend`, `login`, `login/mfa`, `password/forgot`, `password/reset` | Sem sessão |

Não existe papel de administrador. A escalação vertical de privilégio não se aplica, porque toda função está disponível ao próprio usuário sobre os próprios dados.

## Vulnerabilidades encontradas

### V-01 — Limite de requisições por IP burlável com `X-Forwarded-For` forjado
- **Severidade:** Alta (P1) · CVSS 3.1 7.3 (`AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:L/A:L`)
- **Descrição:** a API identifica o cliente pela entrada mais à direita de `X-Forwarded-For` (`TRUST_PROXY_HEADERS=true`). O BFF copiava todos os cabeçalhos do navegador para a API, e a borda do Railway não substitui o `X-Forwarded-For` recebido. Bastava mandar um IP inventado em cada requisição para cair sempre num balde de limite novo.
- **Evidência:** em produção, 22 tentativas de login com e-mails `@example.com` inexistentes, cada uma com `X-Forwarded-For: 203.0.113.N`, deram 22 × `401`, sem nenhum `429` (o limite é 20 a cada 10 min). O controle, sem o cabeçalho, deu `429` a partir da 17ª tentativa.
- **Impacto:** anula os limites de login (20/10 min), cadastro (5/h), recuperação de senha e reenvio de verificação (5/h), além do limite global (300/min). Isso permite credential stuffing em muitas contas, envio massivo de e-mails pela Voryn e, junto com a V-02, força bruta do 2FA. O limite de 5 falhas por conta continuava valendo.
- **Arquivos:** `frontend/src/app/api/[...path]/route.ts`, `frontend/src/lib/upstream-headers.ts` (novo), `.railway/railway.ts`, `docs/SECURITY.md`, `docs/DEPLOY.md`.
- **Correção:** o BFF descarta todo cabeçalho de endereço vindo do cliente (`X-Forwarded-For`, `X-Real-IP`, `Forwarded`, `True-Client-IP`, `CF-Connecting-IP`…) e escreve um `X-Forwarded-For` com um único IP, lido do cabeçalho que a borda sobrescreve. Esse cabeçalho é configurável em `CLIENT_IP_HEADER`, com padrão `x-real-ip`. Valores que não parecem um IP são ignorados. Sem esse cabeçalho, todos os clientes compartilham um balde: a falha é mais restritiva, nunca burlável.
- **Teste:** `upstream-headers.test.ts` (6 casos). DAST local pela pilha completa (BFF → API, limites de produção): com `X-Forwarded-For` forjado e `X-Real-IP` fixo, `429` na 21ª tentativa; sem `X-Real-IP`, também `429` na 21ª.
- **Status:** corrigido e **validado em produção** em 30/10/2026, após o deploy: 22 tentativas com `X-Forwarded-For` e `X-Real-IP` forjados deram `429` a partir da 21ª.

### V-02 — Tentativas ilimitadas do código 2FA no login
- **Severidade:** Alta (P1) · CVSS 3.1 7.4 (`AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:H/A:N`). O `AC:H` reflete que é preciso ter a senha.
- **Descrição:** cada desafio de MFA aceitava 5 códigos, mas um desafio novo só exigia a senha correta. Um acerto de senha também zerava o contador de falhas da conta, então não havia limite por conta no segundo fator.
- **Evidência:** teste contra o código antigo. Depois de 10 códigos errados em 2 desafios, um terceiro desafio ainda aceitou tentativas e autenticou (`200`).
- **Impacto:** quem obteve a senha (vazamento, phishing) consegue adivinhar o TOTP, com 3 códigos válidos por janela entre 10⁶ possíveis. Com a V-01, sem limite por IP. O 2FA deixava de proteger exatamente no cenário para o qual existe.
- **Arquivos:** `backend/app/modules/auth/service.py`, `backend/tests/test_auth.py`.
- **Correção:** limite de **10 falhas por hora por conta**, somando todos os desafios e IPs. Ao atingir o limite, até o código correto é recusado até a janela passar. A primeira falha envia um e-mail de alerta ao dono, porque errar o código depois de acertar a senha indica que a senha é conhecida.
- **Teste:** `test_mfa_failures_are_limited_per_account_across_challenges`. Falha no código antigo (`200 == 429`) e passa no novo.
- **Status:** corrigido.

### V-03 — Open redirect no parâmetro `next` após o login
- **Severidade:** Média (P2) · CVSS 3.1 6.1 (`AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N`)
- **Descrição:** `safeNext` recusava `//` e `/\`, mas o parser de URL do navegador remove tabs e quebras de linha. `/\t/evil.example` passava pela checagem e virava `//evil.example`. O roteador do Next.js 16 navega para fora do site quando a origem muda (`mpaNavigation`).
- **Evidência:** `https://…/entrar?next=%2F%09%2Fevil.example` resolve para `https://evil.example/` depois de um login legítimo.
- **Impacto:** phishing convincente. A vítima entra no site verdadeiro e cai num clone que pede a senha e o código 2FA "de novo".
- **Arquivos:** `frontend/src/lib/safe-next.ts` (novo), `frontend/src/components/auth/login-form.tsx`.
- **Correção:** o destino é resolvido com `new URL()` contra uma origem de referência e só é aceito se continuar na mesma origem.
- **Teste:** `safe-next.test.ts` (9 casos, inclusive variantes com `\t`, `\n`, `\r` e `\`).
- **Status:** corrigido.

### V-04 — Senhas e chaves de exchange iriam para o Sentry em texto puro
- **Severidade:** Média (P2), latente: o Sentry não está configurado hoje, mas `SENTRY_DSN` é uma opção documentada.
- **Descrição:** o Sentry era iniciado com o padrão `include_local_variables=True`. Os modelos de entrada (`LoginIn`, `ConnectionIn`, `PasswordResetIn`) mostram os campos no `repr()`, e o filtro padrão do Sentry procura nomes de variáveis, não conteúdo.
- **Impacto:** qualquer exceção durante um login ou uma conexão de exchange enviaria a senha ou o segredo da API a um serviço externo, onde ficaria retido.
- **Arquivos:** `backend/app/main.py`, `backend/app/modules/exchange_connections/schemas.py`, `backend/app/modules/exchange_connections/service.py`.
- **Correção:** `include_local_variables=False`. `api_key` e `api_secret` passaram a ser `SecretStr`, mascarados em qualquer `repr`, log ou dump.
- **Teste:** `test_error_reports_exclude_frame_locals` e `test_exchange_credentials_never_appear_in_repr`.
- **Status:** corrigido.

### V-05 — Injeção de conteúdo nos e-mails pelo campo nome
- **Severidade:** Média (P2) · CVSS 3.1 4.3 (`AV:N/AC:L/PR:N/UI:R/S:U/C:N/I:L/A:N`)
- **Descrição:** o cadastro envia um e-mail de verificação, com o nome escolhido, para **qualquer** endereço informado. O HTML era escapado, mas o texto não tinha restrição.
- **Evidência:** um cadastro com e-mail da vítima e nome `Conta bloqueada, acesse www.voryn-suporte.com` gera um e-mail oficial da Voryn com esse texto, e os clientes de e-mail transformam o domínio em link.
- **Impacto:** phishing a partir do domínio legítimo. Antes da V-01, sem limite prático de volume.
- **Arquivos:** `backend/app/modules/users/schemas.py`, `backend/app/modules/auth/schemas.py`.
- **Correção:** `validate_full_name`, compartilhada entre cadastro e perfil, recusa URLs, domínios, e-mails, `<>`, `/` e `\`.
- **Teste:** `test_link_like_names_are_rejected` (5 variantes, cadastro e perfil, sem e-mail enviado) e `test_ordinary_names_are_accepted` (hífen, apóstrofo, acentos, iniciais).
- **Status:** corrigido.

### V-06 — Candles com `NaN`/`Infinity` aceitos ou derrubando a série
- **Severidade:** Baixa (P3). Exige comprometer a Binance ou a conexão TLS.
- **Descrição:** `Decimal("Infinity")` passava pelas checagens de consistência de `parse_klines`. Um único `NaN` gerava exceção fora do `try` e descartava a série inteira.
- **Impacto:** uma resposta adulterada poderia gravar preço infinito, que alimenta indicadores e sinais, ou impedir a atualização dos candles.
- **Arquivo:** `backend/app/modules/market_data/providers/binance.py`.
- **Correção:** linhas com valor não finito são descartadas como as demais inconsistentes.
- **Teste:** `test_binance_parser_drops_non_finite_values`.
- **Status:** corrigido.

### V-07 — Serviços locais do `docker-compose` expostos na rede
- **Severidade:** Baixa (P3), só no ambiente de desenvolvimento.
- **Descrição:** Postgres (senha `voryn`), Redis (sem senha), Mailpit, API e web escutavam em todas as interfaces.
- **Impacto:** qualquer pessoa na mesma rede (Wi-Fi público, escritório) acessava o banco local.
- **Arquivo:** `docker-compose.yml`.
- **Correção:** portas publicadas só em `127.0.0.1`.
- **Teste:** `docker compose config` válido; a pilha local subiu e respondeu em `localhost`.
- **Status:** corrigido.

### V-08 — CI sem permissões mínimas e sem varredura de segurança
- **Severidade:** Baixa (P3).
- **Descrição:** o workflow usava as permissões padrão do `GITHUB_TOKEN` e não tinha nenhuma análise de segredos, código ou dependências.
- **Arquivos:** `.github/workflows/ci.yml`, `.gitleaksignore`, `frontend/Dockerfile`.
- **Correção:** `permissions: contents: read` e um job `security` com Gitleaks (histórico completo), Semgrep (regras para Python, FastAPI, TypeScript, React, Next.js, Dockerfile e segredos), pip-audit e npm audit (`--audit-level=moderate`). Cada etapa foi executada localmente e termina com código 0.
- **Status:** corrigido.

### V-09 — Chaves Binance com restrição de IP eram recusadas
- **Severidade:** Baixa (P3): usabilidade de segurança.
- **Descrição:** a flag `ipRestrict` (restrição da chave a IPs conhecidos) era contada como permissão de escrita, então a chave mais segura era rejeitada.
- **Arquivo:** `backend/app/modules/exchange_connections/connectors/binance.py`.
- **Correção:** `ipRestrict` entrou entre as flags neutras. Flags desconhecidas continuam sendo tratadas como escrita.
- **Teste:** `test_ip_restricted_read_only_key_is_accepted`; o teste existente de flags desconhecidas continua passando.
- **Status:** corrigido.

## Áreas verificadas sem vulnerabilidade

| Área | Verificação |
|---|---|
| Autorização (BOLA/IDOR) | Todas as rotas com identificador, testadas com uma segunda conta: carteiras, transações (inclusive o ID de outra pessoa pela própria carteira), insights, risco, cenários, importação CSV, alertas, notificações (IDs sequenciais), watchlists, backtests, conversas da IA, conexões de exchange (detalhe, registros, sincronização, exclusão) e sessões. Recursos de outra pessoa respondem `404`. |
| Autenticação obrigatória | Novo teste percorre **todas** as rotas da API e exige `401` sem sessão, exceto 8 rotas públicas listadas. Validado por mutação: tirar a autenticação de uma rota faz o teste falhar. |
| Injeção | SQLAlchemy com parâmetros em todas as consultas; nenhum SQL montado com texto do usuário. Sem `eval`, shell ou caminhos de arquivo vindos do usuário. |
| Mass assignment | Schemas Pydantic explícitos; `user_id` e `portfolio_id` vêm sempre da sessão ou do recurso verificado. |
| XSS | Nenhum `dangerouslySetInnerHTML`; markdown da IA renderizado sem HTML bruto; CSP aplicada. |
| SSRF | Endereços dos provedores vêm só da configuração; nenhuma URL vinda do usuário é acessada. |
| Sessão | Token aleatório de 256 bits, guardado como HMAC; expiração absoluta e por inatividade; sessões revogadas ao trocar ou redefinir a senha; sem session fixation (o token é emitido no login). |
| Enumeração | Respostas e tempos iguais para e-mails existentes e inexistentes no cadastro, no login e na recuperação de senha. |
| Credenciais de exchange | Cifradas (Fernet com rotação), nunca devolvidas ao navegador, identificadas por HMAC e pelos 4 últimos caracteres; só chaves somente leitura, verificadas a cada sincronização; sem execução de ordens. |
| Voryn AI | Ferramentas somente leitura, `user_id` vindo da sessão, entradas validadas com `extra="forbid"`, limites por hora, dia e conversa. |
| Recomendações | Sinais calculados no servidor, iguais para todos; dados desatualizados viram "atenção", nunca compra ou venda; desvio entre duas fontes bloqueia o par; parâmetros de backtest validados e isolados por usuário. |
| Produção | Cabeçalhos HSTS, CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`; `Cache-Control: no-store` na API; `/docs` e `/openapi.json` desligados (404); API sem domínio público; contêineres sem root. |
| Segredos no Git | Gitleaks no histórico completo (38 commits): só a `SECRET_KEY` fixa de teste (falso positivo registrado). `backend/.env` está no `.gitignore` e nunca foi versionado. |

## Melhorias implementadas

- BFF reescreve o endereço do cliente (`CLIENT_IP_HEADER`).
- Limite de falhas de 2FA por conta e alerta por e-mail na primeira falha.
- Redirecionamento pós-login validado pelo parser de URL.
- Sentry sem variáveis locais; credenciais de exchange como `SecretStr`.
- Validação de nome contra conteúdo enganoso em e-mails.
- Descarte de valores não finitos nos candles.
- Aceitação de chaves Binance com restrição de IP.
- `docker-compose` restrito a `localhost`.
- Job de segurança no CI (Gitleaks, Semgrep, pip-audit, npm audit) e token só de leitura.
- Teste estrutural de autenticação em todas as rotas e testes de isolamento ampliados.
- `docs/SECURITY.md` e `docs/DEPLOY.md` atualizados.

## Testes executados

| Tipo | Ferramenta | Resultado |
|---|---|---|
| Unitários, integração, autorização e regressão (backend) | pytest com Postgres real | **180 aprovados** |
| Lint e tipos (backend) | ruff, mypy | Sem problemas |
| Unitários (frontend) | Vitest | **28 aprovados** (15 novos) |
| Lint, tipos e build (frontend) | ESLint, `tsc`, `next build` | Sem problemas |
| SAST | Semgrep (~2.000 regras, 303 arquivos) | 1 achado: estágio `dev` do Dockerfile como root, aceito e anotado. 2 arquivos com análise parcial (limitação do parser) |
| SCA | pip-audit (190 pacotes) / npm audit | 0 vulnerabilidades / 3 baixas em ferramenta de build |
| Segredos | Gitleaks (histórico) + regex própria | 0 reais |
| DAST em produção (só leitura) | curl | V-01 confirmada; cookies, cabeçalhos e documentação desligada verificados |
| DAST local (pilha completa, limites de produção) | curl via BFF | Correção da V-01 validada |
| Mutação | Remoção manual da autenticação de uma rota | Detectada pelo teste |

**Cenários de ataque simulados:**
1. **Acesso à carteira de outra pessoa:** bloqueado (`404`).
2. **Roubo de sessão:** cookie `HttpOnly` e `Secure`, token só como HMAC no banco; não há token acessível por JavaScript.
3. **Abuso de API:** **vulnerável** (V-01), corrigido.
4. **Manipulação de recomendações:** sinais e scores não aceitam entrada do cliente.
5. **Exposição de credenciais:** latente via Sentry (V-04), corrigida.
6. **Escalação de privilégio:** não há funções administrativas.
7. **Dados externos maliciosos:** V-06, corrigida.
8. **Prompt injection:** só revisão do desenho, porque a IA está desligada em produção.

**Limitações:**
- O Voryn AI não foi executado.
- O DAST em produção limitou-se a leituras e 44 tentativas de login com contas inexistentes.
- O comportamento da borda do Railway com `X-Real-IP` não pôde ser observado diretamente.
- Nenhum teste de carga ou negação de serviço foi feito.

## Riscos residuais

1. **Validação da V-01 em produção.** O Railway documenta que sobrescreve o `X-Real-IP`, mas há relatos de que, com o CDN deles ativo, o cabeçalho traz o IP do CDN. Nesse caso os clientes compartilhariam baldes: seria mais restritivo, não burlável. Depois do deploy, repetir o teste das 22 tentativas com `X-Real-IP` e `X-Forwarded-For` forjados: deve aparecer `429` na 21ª.
2. **Chave do Resend exposta** em conversa durante o deploy. Gere uma nova no Resend e troque a variável compartilhada `RESEND_API_KEY`.
3. **Bloqueio direcionado de conta.** Qualquer pessoa pode bloquear o login de outra por 15 min (5 falhas) ou o 2FA por 1 h (10 falhas). Isso é intencional (bloqueio temporário, não permanente), mas é um vetor de incômodo.
4. ~~**Ativar 2FA não pedia a senha.**~~ **Resolvido** após aprovação: `/me/mfa/setup` exige a senha (limite de 5 tentativas a cada 15 min) antes de gerar o segredo. Testes: `test_mfa_setup_requires_the_password` e o e2e `two-factor.spec.ts` (desktop e celular).
5. **CSP com `script-src 'unsafe-inline'`**, exigido pelos scripts de inicialização do Next.js. Nonces exigem renderização dinâmica de todas as páginas.
6. **Banco com um único usuário de privilégio total** (padrão do Railway) e sem Row Level Security. O isolamento depende só da aplicação, coberta por testes.
7. **Backups do Postgres:** não verificados. Ativar os backups do volume no Railway e testar uma restauração.
8. **Retenção do `audit_logs`** indefinida (LGPD); falta exportação e exclusão de conta.
9. **CI:** actions referenciadas por tag e imagem `semgrep:latest`, não por hash; 3 alertas npm de baixa severidade em ferramenta de build (`shadcn` → `deepmerge`).
10. **Remetente de e-mail** `onboarding@resend.dev`: só entrega ao dono da conta Resend até haver domínio verificado.

## Próximas recomendações

**Antes do deploy (exige sua aprovação, porque afeta produção):**
1. Mesclar `security/hardening` na `main`. O Railway implanta sozinho. O `CLIENT_IP_HEADER` já tem padrão `x-real-ip`, então não é preciso mudar variáveis.
2. Repetir o teste da V-01 em produção.
3. Trocar a `RESEND_API_KEY`.

**P1:**
- ~~Exigir a senha para ativar o 2FA.~~ Feito.
- Ativar e testar os backups do Postgres.

**P2:**
- Fixar actions do GitHub e imagens de ferramentas por hash.
- Usuário de banco com privilégios mínimos para a aplicação (sem DDL), separado do usuário de migração.
- Prefixo `__Host-` nos cookies de sessão e CSRF.
- Alerta de login em novo dispositivo (já listado como pendência).

**P3:**
- Verificação de senhas vazadas (HIBP, k-anonymity).
- Row Level Security como segunda camada.
- CSP com nonce.
- Política de retenção e exportação de dados (LGPD).
- Sentry também no worker.
- Teste ao vivo de prompt injection quando o Voryn AI for ativado.
