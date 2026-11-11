# Proxy da Binance

A API roda nos EUA, e a Binance bloqueia endereços dos EUA em `api.binance.com`. Este servidor no Brasil, com IP fixo, é o caminho de saída **só** do conector da Binance. Dados de mercado e todo o resto continuam saindo direto.

```
Railway (EUA) ──TLS──▶ Proxy em São Paulo ──túnel CONNECT──▶ api.binance.com
```

O proxy só repassa bytes criptografados: não vê chave, assinatura nem dados da conta. Ele aceita apenas `api.binance.com:443`, com senha.

## 1. Criar o servidor grátis (Oracle Cloud Always Free)

1. Crie a conta em https://www.oracle.com/cloud/free/ e escolha **Brazil East (São Paulo)** como região principal. **Essa escolha não pode ser mudada depois**, e o Always Free só vale nessa região. A Oracle pede cartão para verificação.
2. Em **Compute → Instances → Create instance**:
   - Imagem: **Canonical Ubuntu 24.04**.
   - Shape: `VM.Standard.E2.1.Micro` (AMD, marcado como *Always Free-eligible*). Se aparecer "out of host capacity", tente outro domínio de disponibilidade ou mais tarde.
   - Guarde a chave SSH oferecida.
3. Em **Networking → Reserved public IPs**, reserve um IP e associe à instância. Sem isso, o IP pode mudar e a restrição de IP da sua chave na Binance deixa de funcionar.
4. Na rede da instância, abra **Subnet → Security List → Add Ingress Rules**: TCP, origem `0.0.0.0/0`, portas **80** e **8443**.

**Instâncias ociosas:** a Oracle pode recuperar instâncias Always Free que passem 7 dias com CPU (percentil 95) e rede abaixo de 20%, e um proxy pouco usado se encaixa nisso. A Voryn alerta se o proxy parar de responder. Para reduzir o risco, a saída indicada é converter a conta para *Pay As You Go*: a Oracle informa que recursos dentro dos limites Always Free continuam sem cobrança.

## 2. Instalar

No seu computador, a partir desta pasta:

```bash
scp -i CHAVE.key setup.sh squid.conf.template ubuntu@IP_DO_SERVIDOR:~
ssh -i CHAVE.key ubuntu@IP_DO_SERVIDOR "sudo bash setup.sh"
```

O script começa testando se a Binance aceita o IP do servidor. Se responder qualquer coisa diferente de 200, ele para sem instalar nada e você precisa de outro provedor. No fim, ele confere que a Binance responde pelo proxy e que outros destinos são recusados, e mostra `BINANCE_PROXY_URL` e `BINANCE_EGRESS_IP`.

## 3. Ligar na Voryn

`BINANCE_PROXY_URL` é um segredo. Defina-a sem colar em chats, por exemplo no painel do Railway, nos serviços **`api`** e **`worker`**:

```
BINANCE_PROXY_URL=https://voryn:...@...:8443
BINANCE_EGRESS_IP=...
```

O diálogo "Conectar Binance" passa a mostrar o IP. Ao criar a chave na Binance, restrinja-a a esse IP.

Para desligar, apague `BINANCE_PROXY_URL`: o conector volta a sair direto.

## Manutenção

- **Trocar a senha:** no servidor, `sudo htpasswd /etc/squid/passwords voryn`, depois `sudo systemctl restart squid`, e atualize a variável no Railway.
- **Certificado:** o certbot renova sozinho.
- **Logs:** `/var/log/squid/access.log` guarda só horário, status e destino.

Na região errada, ou com o proxy fora do ar, a conexão da Binance falha com uma mensagem clara e a sincronização seguinte tenta de novo; nenhum dado é perdido.
