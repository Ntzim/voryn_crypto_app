# Conexão com exchanges — metodologia e segurança

Código: `backend/app/modules/exchange_connections/`. Exchange implementada: **Binance** (spot). Novas exchanges entram como novos `ExchangeConnector`, sem mudar a importação nem a conciliação.

## Somente leitura, sempre

- Ao conectar, a Voryn consulta as restrições da chave na própria Binance (`/sapi/v1/account/apiRestrictions`). Qualquer permissão ativa além da leitura é **recusada**, inclusive permissões que a Binance venha a criar no futuro (`enableReading` e `enableFixReadOnly` são as únicas aceitas).
- A verificação se repete a cada sincronização. Se a chave ganhar permissão de escrita, a conexão fica **bloqueada** e para de sincronizar.
- Chave e segredo são cifrados em repouso (Fernet, `ENCRYPTION_KEYS`), nunca voltam ao navegador e aparecem só pelos 4 últimos caracteres. Chaves repetidas são detectadas por um HMAC da chave, sem guardá-la em claro.
- Conectar e desconectar ficam registrados na auditoria. Desconectar apaga as credenciais e os registros sincronizados; as transações já importadas continuam na carteira.

## O que é lido

| Dado | Endpoint | Incremental |
|---|---|---|
| Saldos (livre + bloqueado) | `/api/v3/account` | a cada sincronização |
| Negociações spot contra BRL, USDT, USDC, FDUSD | `/api/v3/myTrades` por mercado | por `fromId`, desde a primeira negociação |
| Depósitos de cripto concluídos | `/sapi/v1/capital/deposit/hisrec` | janelas de 89 dias; 365 dias na primeira vez; 3 dias de sobreposição |
| Saques concluídos | `/sapi/v1/capital/withdraw/history` | idem |

Os mercados consultados são os dos ativos com saldo, dos ativos já vistos em sincronizações anteriores e dos ativos depositados ou sacados. Fora do escopo: Convert, Earn, P2P, Pay, margem e futuros, mercados entre duas criptos (ex.: ETH/BTC) e depósitos em reais. As diferenças que eles deixam aparecem na conciliação.

Cada registro é guardado uma única vez por conexão, identificado pelo id da própria Binance, então sincronizar de novo não duplica nada.

## Como vira transação

| Registro | Transação |
|---|---|
| Negociação contra BRL | compra/venda em BRL pelo preço executado (taxa em BRL entra na própria transação) |
| Negociação contra stablecoin | conversão entre os dois ativos, valorada em USD (1 stablecoin = US$ 1) |
| Comissão em cripto | transação de taxa no ativo cobrado, 1 µs após a negociação |
| Depósito de cripto | depósito valorado pelo fechamento diário (Binance, UTC) do dia; stablecoins a US$ 1 |
| Saque | saque + transação de taxa da rede |

A importação passa pela mesma validação do registro manual, que não aceita saldo negativo. Nada é importado com valores inventados: registros com ativo fora do catálogo, sem preço histórico ou sem saldo suficiente (por exemplo, a venda de moedas compradas antes do período sincronizado) ficam **para revisar**, com o motivo. Depois de registrar manualmente o que falta, a próxima sincronização tenta de novo.

## Conciliação

A cada sincronização, o saldo atual de cada ativo na exchange é comparado com a quantidade que as transações da Voryn atribuem a ela: as importadas e as manuais marcadas com essa exchange, incluindo transferências. A tolerância é de 0,0001% do saldo ou 1e-8. Diferenças são exibidas, nunca corrigidas automaticamente.

## Agendamento

Uma sincronização roda logo após conectar, outra quando o usuário pede (intervalo mínimo de 2 minutos) e todas as conexões são sincronizadas a cada 6 horas pelo worker.

## Coinbase e Kraken

Ainda não implementadas. Na Kraken, a API não permite consultar as permissões de uma chave, então a regra de somente leitura não poderia ser verificada; integrá-la exige outra forma de garantir isso. A Coinbase expõe `key_permissions` e é a próxima candidata.
