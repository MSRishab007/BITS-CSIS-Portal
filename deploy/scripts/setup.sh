#!/usr/bin/env bash
# First-time setup on Ubuntu 22.04 / 24.04. Run from the cloned repository:
#
#   sudo bash deploy/scripts/setup.sh assets.example.bits-pilani.ac.in
#
# (use the server's IP address instead of a host name for an intranet-only
# start). Safe to run again: existing .env, database and bills are kept.
set -euo pipefail

HOST="${1:-}"
if [[ -z "$HOST" ]]; then echo "Usage: sudo bash deploy/scripts/setup.sh <host name or IP>"; exit 1; fi
if [[ $EUID -ne 0 ]]; then echo "Please run with sudo."; exit 1; fi

BASE=/srv/asset-portal
APP=$BASE/app
SRC="$(cd "$(dirname "$0")/../.." && pwd)"

echo "==> Packages"
apt-get update -q
apt-get install -y -q python3 python3-venv python3-dev nginx git

echo "==> User and folders"
id portal >/dev/null 2>&1 || useradd --system --home "$BASE" --shell /usr/sbin/nologin portal
mkdir -p "$BASE"/{data/media,logs,backups}
if [[ "$SRC" != "$APP" ]]; then
  if [[ -e "$APP" ]]; then echo "$APP already exists; run this script from inside it instead."; exit 1; fi
  cp -a "$SRC" "$APP"
fi
chown -R portal:portal "$BASE"
# Nginx (www-data) must read static files and bills, nothing else.
chmod 750 "$BASE" "$BASE/data" "$BASE/backups" "$BASE/logs"
usermod -aG portal www-data

echo "==> Python environment"
sudo -u portal python3 -m venv "$BASE/venv"
sudo -u portal "$BASE/venv/bin/pip" install -q --upgrade pip
sudo -u portal "$BASE/venv/bin/pip" install -q -r "$APP/requirements.txt"

echo "==> Settings (.env)"
if [[ ! -f "$APP/.env" ]]; then
  SECRET=$("$BASE/venv/bin/python" -c "import secrets; print(secrets.token_urlsafe(50))")
  cat > "$APP/.env" <<ENV
SECRET_KEY=$SECRET
DEBUG=False
ALLOWED_HOSTS=$HOST
CSRF_TRUSTED_ORIGINS=http://$HOST,https://$HOST
SECURE_COOKIES=False
ALLOWED_EMAIL_DOMAINS=pilani.bits-pilani.ac.in
DEPARTMENT_NAME="Department of Computer Science & Information Systems"
DEPARTMENT_SHORT=CSIS
DATABASE_PATH=$BASE/data/db.sqlite3
MEDIA_ROOT=$BASE/data/media
LOG_DIR=$BASE/logs
BACKUP_DIR=$BASE/backups
BACKUP_KEEP_DAYS=14
BEHIND_PROXY=True
SERVE_BILLS_WITH_NGINX=True
STATIC_MANIFEST=True
SECURE_HSTS_SECONDS=0
ENV
  chown portal:portal "$APP/.env"; chmod 600 "$APP/.env"
  echo "    created $APP/.env"
else
  echo "    keeping existing $APP/.env"
fi

echo "==> Database and static files"
cd "$APP"
sudo -u portal "$BASE/venv/bin/python" manage.py migrate --noinput
sudo -u portal "$BASE/venv/bin/python" manage.py collectstatic --noinput -v0
sudo -u portal "$BASE/venv/bin/python" manage.py check --deploy || true

echo "==> Services"
cp deploy/systemd/asset-portal.service deploy/systemd/asset-portal-backup.service deploy/systemd/asset-portal-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now asset-portal asset-portal-backup.timer

echo "==> Nginx"
sed "s/assets.example.bits-pilani.ac.in/$HOST/" deploy/nginx/asset-portal.conf > /etc/nginx/sites-available/asset-portal.conf
ln -sf /etc/nginx/sites-available/asset-portal.conf /etc/nginx/sites-enabled/asset-portal.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx   # restart (not reload) so the new group membership applies

echo
echo "Done. Next:"
echo "  1. Create your account:  cd $APP && sudo -u portal $BASE/venv/bin/python manage.py createsuperuser"
echo "  2. Open http://$HOST/ and sign in."
echo "  3. Set up HTTPS (DEPLOYMENT.md, step 6)."
