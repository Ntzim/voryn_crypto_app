# Deploy no Railway

A Voryn roda no Railway como seis serviços em um projeto, todos a partir deste repositório:

| Serviço | Origem | Acesso | Função |
|---|---|---|---|
| `web` | `frontend/` (Dockerfile) | **público** (domínio HTTPS) | Next.js; o BFF repassa `/api/*` para a API pela rede privada |
| `api` | `backend/` (Dockerfile) | **só rede privada** | FastAPI; roda as migrations antes de cada deploy |
| `worker` | `backend/`, outro comando | — | Celery: mercado, sinais, alertas, e-mails, backtests, sync de exchanges |
| `beat` | `backend/`, outro comando | — | agendador (exatamente 1 réplica) |
| `postgres` | banco gerenciado | privado | dados |
| `redis` | banco gerenciado | privado | fila, cache, limites de requisição |

A configuração está versionada em [`.railway/railway.ts`](../.railway/railway.ts), no formato Infrastructure as Code do Railway. É o formato atual: `railway.toml`/`railway.json` estão obsoletos e deixam de ser lidos em 2026-12-01.

## 1. Antes de começar

- **Código na branch `main` do GitHub.** O arquivo de infraestrutura implanta `Ntzim/voryn_crypto_app@main`. Faça o merge da branch de desenvolvimento, ou troque `BRANCH` em `.railway/railway.ts`.
- **Railway CLI 5.x:** `npm i -g @railway/cli`, depois `railway --version`.
- **Conta no [Resend](https://resend.com)** para os e-mails de confirmação e de recuperação de senha. O Railway bloqueia SMTP de saída no plano Hobby. O Resend envia por HTTPS e funciona em qualquer plano. Verifique o seu domínio no Resend (registros DNS) e crie uma API key com permissão de envio. Sem domínio verificado, o Resend só entrega para o seu próprio e-mail.
  - No plano Pro, também dá para usar SMTP: `EMAIL_BACKEND=smtp` e `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_STARTTLS`.

## 2. Segredos

Gere uma vez por ambiente e **não** versione o resultado:

```bash
cd backend
uv run python scripts/generate_secrets.py
```

No projeto do Railway, abra **Project Settings → Shared Variables** do ambiente `production` e crie:

| Variável | Valor |
|---|---|
| `SECRET_KEY` | gerado acima |
| `ENCRYPTION_KEYS` | gerado acima (cifra 2FA e chaves de exchange; **não perca**: sem ele esses dados não podem ser lidos) |
| `FRONTEND_URL` | endereço público do `web`, ex.: `https://voryn.up.railway.app` ou o seu domínio (ajuste depois do passo 4) |
| `EMAIL_FROM` | remetente verificado no Resend, ex.: `Voryn <no-reply@seudominio.com>` |
| `RESEND_API_KEY` | chave do Resend |

`api`, `worker` e `beat` usam os mesmos valores. O worker também assina tokens e decifra as chaves das exchanges.

## 3. Criar os serviços

```bash
railway login
railway link          # escolha ou crie o projeto e o ambiente "production"
railway config plan   # revise: postgres, redis, api, worker, beat, web
railway config apply
```

O arquivo define para cada serviço:

- **`api`:** pre-deploy `alembic upgrade head` (se falhar, o deploy para e a versão anterior continua no ar); health check em `/health/ready` (banco e Redis); `PORT=8000`; `HOST=::`, que escuta em IPv6 e IPv4 na rede privada.
- **`worker`:** `celery ... worker --concurrency=2 -Q voryn`.
- **`beat`:** `celery ... beat`, 1 réplica.
- **`web`:** `API_PRIVATE_HOST` aponta para o domínio privado da `api` (referência, sem endereço fixo); health check em `/entrar`.
- **Watch paths:** mudanças só em `frontend/` não reimplantam o backend, e vice-versa.

> **Sem a CLI:** crie os serviços pelo painel com os mesmos valores. Para `api`, `worker` e `beat`: repositório, Root Directory `backend`, comando de início acima e as variáveis da tabela abaixo. Para o `web`: Root Directory `frontend`, `API_PRIVATE_HOST=${{api.RAILWAY_PRIVATE_DOMAIN}}`, `API_PRIVATE_PORT=8000` e `CLIENT_IP_HEADER=x-real-ip` (o cabeçalho que a borda do Railway sobrescreve; o limite de requisições por IP depende dele, veja [SECURITY.md](SECURITY.md#proteção-contra-abuso-redis-janela-fixa)).

Variáveis de `api`, `worker` e `beat` (o arquivo já as define):

```
ENVIRONMENT=production
DATABASE_URL=${{postgres.DATABASE_URL}}
REDIS_URL=${{redis.REDIS_URL}}
SECRET_KEY=${{shared.SECRET_KEY}}
ENCRYPTION_KEYS=${{shared.ENCRYPTION_KEYS}}
FRONTEND_URL=${{shared.FRONTEND_URL}}
EMAIL_BACKEND=resend
EMAIL_FROM=${{shared.EMAIL_FROM}}
RESEND_API_KEY=${{shared.RESEND_API_KEY}}
TRUST_PROXY_HEADERS=true
```

Só na `api`: `PORT=8000` e `HOST=::`.

## 4. Domínio público

1. No serviço **`web`** → Settings → Networking → **Generate Domain**, ou adicione o seu domínio e configure o DNS indicado.
2. Atualize a shared variable `FRONTEND_URL` com esse endereço. Ele aparece nos links dos e-mails.
3. **Não** gere domínio para a `api`. Ela deve ser acessível só pelo `web`. O limite de requisições por IP depende disso: a API confia no `X-Forwarded-For` que o BFF repassa.

## 5. Variáveis opcionais

| Variável | Serviço | Efeito |
|---|---|---|
| `ANTHROPIC_API_KEY` | `api` | habilita o Voryn AI (modelo `claude-opus-5-5`; ajuste com `AI_MODEL`, `AI_EFFORT`) |
| `COINGECKO_API_KEY` + `COINGECKO_API_PLAN=demo` | `api`, `worker` | mais limite de requisições na CoinGecko |
| `SENTRY_DSN` | `api`, `worker`, `beat` | captura de erros |

O arquivo de infraestrutura mantém os valores que você definir no painel para essas variáveis (`preserve()`).

## 6. Verificação depois do primeiro deploy

1. **Logs da `api`:** `Running upgrade ...` no pre-deploy, depois `Application startup complete`. Se a configuração estiver incompleta, a API **não sobe** e o log lista exatamente o que falta.
2. **Logs do `worker`:** `celery@... ready` e `market_sync_completed` cerca de 1 minuto depois.
3. **Logs do `beat`:** `beat: Starting...`.
4. **Conta:** abra o domínio, crie uma conta e confirme o e-mail. Se o e-mail não chegar, procure `email_send_failed` nos logs do worker; a mensagem do Resend explica o motivo (domínio não verificado, remetente inválido). O worker tenta de novo, com espera crescente.
5. **Páginas:** dashboard, mercado e análise mostram dados reais. Sinais aparecem depois da primeira rodada (até 30 min).

## Operação

- **Escala:** `api` e `worker` podem ter mais réplicas; as sessões ficam no banco e no Redis. O `beat` deve ficar sempre em **1**.
- **Backups:** ative os backups do volume do Postgres no Railway e teste uma restauração ([SECURITY.md](SECURITY.md#backup-e-retenção)).
- **Rotação de segredos:**
  - Trocar `SECRET_KEY` desconecta todos os usuários.
  - Para `ENCRYPTION_KEYS`, use `nova,antiga`: a primeira cifra e todas são aceitas para decifrar. Retire a antiga só depois de recifrar os dados.
- **Migrations:** rodam sozinhas no pre-deploy da `api`. Sempre crie migrations compatíveis com a versão anterior do código, porque o `worker` pode reiniciar um pouco depois da `api`.

## Problemas comuns

| Sintoma | Causa provável |
|---|---|
| `web` responde 502 "Não foi possível conectar aos servidores" | `api` fora do ar ou em deploy; confira os logs e as variáveis `API_PRIVATE_HOST`/`API_PRIVATE_PORT` do `web` |
| Deploy da `api` falha no health check | banco ou Redis inacessível (`/health/ready` mostra qual); variáveis `DATABASE_URL`/`REDIS_URL` |
| `Invalid production configuration: ...` | falta um segredo ou um valor seguro; a mensagem diz qual |
| Todos os usuários batem no limite de requisições | `TRUST_PROXY_HEADERS` ausente, ou a `api` exposta publicamente |
| E-mails não chegam | domínio não verificado no Resend, ou `EMAIL_FROM` fora do domínio verificado |
