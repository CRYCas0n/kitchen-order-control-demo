#!/usr/bin/env bash
set -euo pipefail
cd /opt/kitchen-control
if ! id kitchen-control >/dev/null 2>&1; then
    useradd --system --home-dir /opt/kitchen-control --shell /usr/sbin/nologin kitchen-control
fi
chown root:kitchen-control /opt/kitchen-control
chmod 750 /opt/kitchen-control
chown root:kitchen-control .env
chmod 640 .env
python3 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements-lock.txt
install -d -o kitchen-control -g kitchen-control -m 750 data
runuser -u kitchen-control -- .venv/bin/python -m scripts.seed
.venv/bin/python -m unittest discover -s tests -q
install -m 644 deploy/kitchen-control.service /etc/systemd/system/kitchen-control.service
systemd-analyze verify /etc/systemd/system/kitchen-control.service
systemctl daemon-reload
systemctl enable --now kitchen-control.service
systemctl restart kitchen-control.service
for attempt in $(seq 1 30); do
    if curl -fsS http://172.18.0.1:18080/api/health; then break; fi
    sleep 1
done
curl -fsS http://172.18.0.1:18080/api/health
# Keep every existing virtual host byte-for-byte; back up before append.
if ! grep -q '^kitchen\.45-67-202-162\.sslip\.io ' /opt/caddy/Caddyfile; then
    backup_file="/opt/caddy/Caddyfile.before-kitchen-$(date -u +%Y%m%dT%H%M%SZ)"
    cp -p /opt/caddy/Caddyfile "$backup_file"
    printf '\n' >> /opt/caddy/Caddyfile
    cat deploy/Caddyfile.snippet >> /opt/caddy/Caddyfile
    if ! docker exec caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile; then
        cat "$backup_file" > /opt/caddy/Caddyfile
        exit 1
    fi
    if ! docker exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile; then
        cat "$backup_file" > /opt/caddy/Caddyfile
        docker exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
        exit 1
    fi
fi
systemctl is-active kitchen-control.service
systemctl is-enabled kitchen-control.service
