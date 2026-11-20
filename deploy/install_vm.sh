#!/usr/bin/env bash
set -euo pipefail
# Run as root on the dedicated CryptoX VM, after uploading /tmp/cryptox.tgz.
API_HOST=${1:?API hostname required}
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip caddy
id cryptox >/dev/null 2>&1 || useradd --system --home-dir /opt/cryptox --create-home --shell /usr/sbin/nologin cryptox
install -d -o cryptox -g cryptox /opt/cryptox /opt/cryptox/data/paper /opt/cryptox/logs
if systemctl is-active --quiet cryptox; then systemctl stop cryptox; fi
tar -xzf /tmp/cryptox.tgz -C /opt/cryptox
chown -R cryptox:cryptox /opt/cryptox
# --clear: recreating a venv in place over an existing one leaves ensurepip unable to
# upgrade pip (observed on Debian's python3.11.2), so always start from an empty venv.
sudo -u cryptox python3 -m venv --clear /opt/cryptox/.venv
sudo -u cryptox /opt/cryptox/.venv/bin/python -m pip install --quiet --upgrade 'pip>=26.2' 'setuptools>=84.1.0'
sudo -u cryptox /opt/cryptox/.venv/bin/pip install --quiet -e /opt/cryptox
cat > /opt/cryptox/.env <<'ENV'
LIVE_TRADING=false
DASHBOARD_ALLOWED_EMAILS=admin@cryptox.com
DASHBOARD_ALLOWED_ORIGINS=https://cryptox-5a848.web.app,https://cryptox-5a848.firebaseapp.com
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8000
ENV
chown cryptox:cryptox /opt/cryptox/.env
chmod 600 /opt/cryptox/.env
cp /opt/cryptox/deploy/cryptox.service /etc/systemd/system/cryptox.service
cat > /etc/caddy/Caddyfile <<CADDY
$API_HOST {
    reverse_proxy 127.0.0.1:8000
    header {
        Strict-Transport-Security "max-age=31536000"
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        Referrer-Policy same-origin
        -Server
    }
}
CADDY
caddy validate --config /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable --now cryptox caddy
systemctl reload caddy
systemctl is-active cryptox caddy
