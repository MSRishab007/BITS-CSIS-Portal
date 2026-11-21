#!/usr/bin/env bash
# Deploy the latest code from GitHub. Run on the server:
#
#   sudo bash /srv/asset-portal/app/deploy/scripts/update.sh
#
# Takes a backup first, then pulls, installs packages, migrates, collects
# static files and restarts gracefully (no dropped requests).
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo "Please run with sudo."; exit 1; fi

BASE=/srv/asset-portal
APP=$BASE/app
PY=$BASE/venv/bin/python
as_portal() { sudo -u portal "$@"; }
cd "$APP"

echo "==> Backup before updating"
as_portal "$PY" manage.py portal_backup --keep-days 0

echo "==> Pull latest code"
before=$(as_portal git rev-parse --short HEAD)
as_portal git pull --ff-only
after=$(as_portal git rev-parse --short HEAD)
echo "    $before -> $after"

echo "==> Packages, migrations, static files"
as_portal "$BASE/venv/bin/pip" install -q -r requirements.txt
as_portal "$PY" manage.py migrate --noinput
as_portal "$PY" manage.py collectstatic --noinput -v0
as_portal "$PY" manage.py check --deploy --fail-level ERROR

echo "==> Restart"
cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl reload-or-restart asset-portal
sleep 2
systemctl is-active --quiet asset-portal && echo "    portal is running ($after)"
curl -fsS -H "Host: $(grep -m1 '^ALLOWED_HOSTS=' .env | cut -d= -f2 | cut -d, -f1)" http://127.0.0.1/healthz/ && echo
