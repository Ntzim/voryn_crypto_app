# Segurança

## Autenticação

| Controle | Implementação |
|---|---|
| Hash de senha | argon2id (`argon2-cffi`), rehash automático quando parâmetros mudam; executado em thread para não bloquear o event loop |
| Política de senha | 10–128 caracteres, bloqueio de senhas triviais (NIST SP 800-63B: comprimento > regras de composição) |
| Sessão | token opaco aleatório (256 bits) em cookie `HttpOnly; SameSite=Lax; Secure`; no banco só o HMAC-SHA256 (chave `SECRET_KEY`). Expiração absoluta 30 dias, por inatividade 7 dias. Revogável individualmente |
| CSRF | double-submit: cookie `voryn_csrf` + header `X-CSRF-Token` obrigatório em todo método não seguro sob `/api/` (inclui login, prevenindo *login CSRF*) |
| Verificação de e-mail | obrigatória antes do primeiro login; link de uso único, expira em 48 h |
| Recuperação de senha | link de uso único, expira em 30 min; ao redefinir, todas as sessões são encerradas e o usuário é notificado |
| Enumeração de contas | cadastro, "esqueci a senha" e "reenviar verificação" respondem igual para e-mails existentes e inexistentes; o hash de senha é calculado nos dois caminhos para igualar o tempo de resposta; login sempre verifica contra um hash (fictício quando o usuário não existe) |
| 2FA | TOTP (RFC 6238), segredo cifrado com Fernet (`ENCRYPTION_KEYS`, com rotação via MultiFernet), tolerância de ±1 passo, **cada código só pode ser usado uma vez** (proteção a replay em Redis). 10 códigos de recuperação de uso único, armazenados como HMAC. Desativar exige senha + segundo fator |
| Desafio MFA | após a senha, um token temporário (5 min, máx. 5 tentativas) — nenhuma sessão é criada antes do segundo fator |

## Proteção contra abuso (Redis, janela fixa)

| Ação | Limite |
|---|---|
| Qualquer rota `/api/` | 300/min por IP |
| Login | 20 / 10 min por IP; 5 falhas / 15 min por conta (bloqueio temporário, não permanente, para evitar DoS de conta) |
| Cadastro | 5 / h por IP |
| Esqueci a senha / reenviar verificação | 5 / h por IP; 3 e-mails / h por conta (silencioso) |
| Reautenticação (troca de senha, desativar 2FA) | 5 / 15 min por usuário |
| Verificação de segundo fator | 10 / 15 min por usuário |

IP do cliente: por padrão `request.client`. Com `TRUST_PROXY_HEADERS=true` (somente atrás de proxy controlado), usa a entrada **mais à direita** de `X-Forwarded-For`, a única que o cliente não consegue forjar.

Backtests: 10 execuções/h por usuário. Conexões de exchange: 5 por hora; sincronização manual a cada 2 min no mínimo.

Voryn AI: 30 mensagens/h e 150/dia por usuário, 30 mensagens por conversa, rodadas de ferramentas limitadas por resposta.

## Voryn AI

- As ferramentas são **somente leitura**. Não existe caminho do modelo para criar, alterar ou apagar dados, nem para enviar ordens.
- As ferramentas recebem o `user_id` da sessão. O modelo não escolhe de quem são os dados consultados.
- Resultados de ferramentas e textos do usuário (notas, nomes) são dados, não instruções. O prompt de sistema determina isso, e nenhuma ferramenta tem efeito colateral que uma injeção possa explorar.
- A entrada das ferramentas é validada por esquema (`extra="forbid"`) antes da execução; entradas inválidas voltam ao modelo como erro.
- Markdown gerado pelo modelo é renderizado sem HTML bruto.
- `ANTHROPIC_API_KEY` só existe no backend. Conversas são apagadas com o usuário (CASCADE) ou por ele.

## Isolamento de dados

Toda consulta a dados do usuário filtra por `user_id` vindo da sessão — nunca de parâmetros da requisição. Recursos de outro usuário respondem **404** (não 403), para não confirmar sua existência. Há teste automatizado cobrindo tentativa de revogar sessão de outro usuário.

## Segredos

- `SECRET_KEY`: HMAC de tokens. `ENCRYPTION_KEYS`: Fernet para segredos em repouso (TOTP hoje; chaves de exchange na Fase 6). Em produção a aplicação **recusa iniciar** sem valores fortes.
- Credenciais de exchange: só chaves **somente leitura**, verificadas na própria exchange ao conectar e a cada sincronização. Qualquer outra permissão, inclusive uma desconhecida, é recusada ou bloqueia a conexão. Chave e segredo ficam cifrados (Fernet), nunca voltam ao navegador e são identificados por HMAC e pelos 4 últimos caracteres. Conectar e desconectar entram na auditoria ([EXCHANGES.md](EXCHANGES.md)).
- Auditoria (`audit_logs`) nunca registra senhas, tokens ou códigos.

## Cabeçalhos e transporte

API: `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Cache-Control: no-store`, HSTS em produção. Web: CSP e cabeçalhos equivalentes em `next.config.ts`. `/docs` e `/openapi.json` ficam desabilitados em produção.

## Auditoria

Eventos registrados: cadastro, verificação de e-mail, login (sucesso/falha, com motivo), logout, pedido e redefinição de senha, troca de senha, ativação/desativação de 2FA, uso de código de recuperação, revogação de sessão, alteração de perfil e preferências. Cada evento grava usuário, IP, user-agent e contexto não sensível.

## Backup e retenção

- PostgreSQL: backups automáticos do provedor (Railway) + `pg_dump` diário recomendado para armazenamento externo cifrado; testar restauração mensalmente.
- `market_prices` (histórico de cotações intradiárias): 7 dias (`MARKET_HISTORY_RETENTION_DAYS`). `fx_rates`: 1 ano. Sessões/tokens expirados: removidos 30 dias após expirar. `audit_logs`: mantidos (política de expurgo a definir junto com termos de uso/LGPD).

## Pendências conhecidas

- Notificação de login em novo dispositivo.
- Política formal de exclusão de conta e exportação de dados (LGPD) — prevista para antes do lançamento comercial.
- Verificação de senhas vazadas (k-anonymity, HIBP) — opcional.
