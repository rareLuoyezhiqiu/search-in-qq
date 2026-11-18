#!/usr/bin/env bash
# Run as root after copying backend to /opt/shitu and installing its dependencies.
set -euo pipefail
id shitu >/dev/null 2>&1 || useradd --system --home /opt/shitu --shell /usr/sbin/nologin shitu
chmod 755 /opt/shitu
install -d -o shitu -g shitu -m 700 /var/lib/shitu
if [ ! -f /etc/shitu.env ]; then
  umask 077
  printf 'DATA_DIR=/var/lib/shitu\nINGEST_TOKEN=%s\n' "$(openssl rand -hex 32)" > /etc/shitu.env
fi
cd /opt/shitu/backend
DATA_DIR=/var/lib/shitu /opt/shitu/venv/bin/alembic upgrade head
DATA_DIR=/var/lib/shitu /opt/shitu/venv/bin/python - <<'PY'
import secrets
from pathlib import Path
from collector.api import passwords
from collector.db import Store,rows,run
with Store().tx() as c:
    if not rows(c,'SELECT password FROM settings')[0]['password']:
        password=secrets.token_urlsafe(24)
        run(c,'UPDATE settings SET password=:p',p=passwords.hash(password))
        p=Path('/opt/shitu/admin-password.txt')
        p.write_text(password+'\n')
        p.chmod(0o600)
PY
chown -R shitu:shitu /var/lib/shitu
for kind in api worker; do
  port=18000
  [ "$kind" = worker ] && port=18001
  cat > "/etc/systemd/system/shitu-$kind.service" <<EOF
[Unit]
Description=Shitu $kind
After=network-online.target
Wants=network-online.target
[Service]
User=shitu
Group=shitu
WorkingDirectory=/opt/shitu/backend
EnvironmentFile=/etc/shitu.env
ExecStart=/opt/shitu/venv/bin/uvicorn collector.$kind:app --host 127.0.0.1 --port $port --no-access-log
Restart=always
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/shitu
UMask=0077
[Install]
WantedBy=multi-user.target
EOF
done
systemctl daemon-reload
systemctl enable --now shitu-api shitu-worker
