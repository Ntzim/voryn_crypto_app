#!/usr/bin/env bash
# Sets up the Voryn egress proxy on a fresh Ubuntu 22.04/24.04 server in Brazil.
#
#   sudo bash setup.sh [domain]
#
# Without a domain it uses <ip>.sslip.io. Ports 80 and 8443 must already be open in the cloud
# provider's firewall (on Oracle: the subnet's security list). Prints BINANCE_PROXY_URL at the end
# and keeps it in /root/voryn-proxy.env; the password is not stored anywhere else in clear.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Rode como root: sudo bash setup.sh" >&2; exit 1; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$HERE/squid.conf.template" ] || { echo "squid.conf.template precisa estar ao lado deste script." >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive
USERNAME=voryn
TLS_DIR=/etc/squid/tls
PORT=8443

command -v curl >/dev/null || { apt-get update -qq; apt-get install -y -qq curl; }

# Step 0: is this server's address accepted by Binance? Stop before installing anything if not.
echo "==> Testando se a Binance aceita o IP deste servidor"
BINANCE_STATUS="$(curl -s -m 20 -o /dev/null -w '%{http_code}' https://api.binance.com/api/v3/time || true)"
if [ "$BINANCE_STATUS" != "200" ]; then
  echo "A Binance respondeu HTTP $BINANCE_STATUS para este servidor (esperado: 200)." >&2
  echo "O IP ou a região está bloqueado: use outro provedor ou região. Nada foi instalado." >&2
  exit 2
fi

IP="$(curl -4 -s -m 20 https://api.ipify.org)"
[[ "$IP" =~ ^[0-9]+(\.[0-9]+){3}$ ]] || { echo "Não foi possível descobrir o IP público." >&2; exit 1; }
DOMAIN="${1:-${IP//./-}.sslip.io}"
echo "==> IP $IP, domínio $DOMAIN"

echo "==> Instalando pacotes"
echo iptables-persistent iptables-persistent/autosave_v4 boolean true | debconf-set-selections
echo iptables-persistent iptables-persistent/autosave_v6 boolean true | debconf-set-selections
apt-get update -qq
apt-get install -y -qq squid-openssl apache2-utils certbot fail2ban unattended-upgrades iptables-persistent openssl
systemctl stop squid || true

echo "==> Liberando as portas no firewall do sistema"
# Oracle's Ubuntu images end INPUT with a REJECT rule, so these go on top of it.
for p in 80 "$PORT"; do
  iptables -C INPUT -p tcp --dport "$p" -m conntrack --ctstate NEW -j ACCEPT 2>/dev/null ||
    iptables -I INPUT 1 -p tcp --dport "$p" -m conntrack --ctstate NEW -j ACCEPT
done
netfilter-persistent save >/dev/null

echo "==> Emitindo o certificado TLS"
cat >/usr/local/bin/voryn-proxy-cert-hook <<EOF
#!/usr/bin/env bash
# Copies the renewed certificate where Squid (unprivileged user) can read it.
set -euo pipefail
install -d -o proxy -g proxy -m 750 $TLS_DIR
install -o proxy -g proxy -m 640 /etc/letsencrypt/live/$DOMAIN/fullchain.pem $TLS_DIR/fullchain.pem
install -o proxy -g proxy -m 640 /etc/letsencrypt/live/$DOMAIN/privkey.pem $TLS_DIR/privkey.pem
systemctl is-active --quiet squid && systemctl restart squid || true
EOF
chmod 755 /usr/local/bin/voryn-proxy-cert-hook
if ! certbot certonly --standalone --non-interactive --agree-tos --register-unsafely-without-email \
  --preferred-challenges http -d "$DOMAIN" --deploy-hook /usr/local/bin/voryn-proxy-cert-hook; then
  echo "O certificado falhou. Confira se a porta 80 está aberta no firewall do provedor." >&2
  exit 3
fi
/usr/local/bin/voryn-proxy-cert-hook

echo "==> Configurando o Squid"
PASSWORD="$(openssl rand -hex 24)"
printf '%s' "$PASSWORD" | htpasswd -c -i /etc/squid/passwords "$USERNAME" 2>/dev/null
chown proxy:proxy /etc/squid/passwords
chmod 640 /etc/squid/passwords
sed "s#__TLS_DIR__#$TLS_DIR#g" "$HERE/squid.conf.template" >/etc/squid/squid.conf
squid -k parse -f /etc/squid/squid.conf >/dev/null 2>&1 || { squid -k parse -f /etc/squid/squid.conf; exit 4; }
systemctl enable --now squid
systemctl restart squid
systemctl enable --now fail2ban unattended-upgrades >/dev/null
sleep 2

echo "==> Testando o proxy"
PROXY_URL="https://$USERNAME:$PASSWORD@$DOMAIN:$PORT"
THROUGH="$(curl -s -m 20 -o /dev/null -w '%{http_code}' --proxy "$PROXY_URL" https://api.binance.com/api/v3/time || true)"
ELSEWHERE="$(curl -s -m 20 -o /dev/null -w '%{http_code}' --proxy "$PROXY_URL" https://example.com || true)"
if [ "$THROUGH" != "200" ]; then
  echo "A chamada à Binance pelo proxy respondeu HTTP $THROUGH (esperado: 200)." >&2
  echo "Confira se a porta $PORT está aberta no firewall do provedor." >&2
  exit 5
fi
if [ "$ELSEWHERE" = "200" ]; then
  echo "ERRO: o proxy aceitou outro destino. Ele não deve ficar no ar assim." >&2
  systemctl stop squid
  exit 6
fi

umask 077
cat >/root/voryn-proxy.env <<EOF
BINANCE_PROXY_URL=$PROXY_URL
BINANCE_EGRESS_IP=$IP
EOF

echo
echo "Pronto. Binance pelo proxy: OK. Outros destinos: bloqueados."
echo "Os valores abaixo também estão em /root/voryn-proxy.env. BINANCE_PROXY_URL é um segredo."
echo
cat /root/voryn-proxy.env
