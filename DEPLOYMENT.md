# Deploying on the college server

This guide sets the portal up on **Ubuntu 22.04 or 24.04** behind **Nginx** with
**Gunicorn**, nightly backups and HTTPS. It takes about 20–30 minutes.

```
Browser ──HTTPS──▶ Nginx ──unix socket──▶ Gunicorn (Django) ──▶ SQLite (data/db.sqlite3)
                     │                                     └──▶ bills (data/media/)
                     └── /static/  (CSS, JS, logo)  served directly, cached
                     └── bills     sent by Nginx only after Django checks permission
```

| Path | What's there |
|---|---|
| `/srv/asset-portal/app/` | the code (this repository) and `.env` |
| `/srv/asset-portal/venv/` | Python packages |
| `/srv/asset-portal/data/` | **the database and uploaded bills: the only irreplaceable data** |
| `/srv/asset-portal/backups/` | nightly backups (14 days kept) |
| `/srv/asset-portal/logs/` | application log (`portal.log`) |

Everything runs as a dedicated `portal` user with no login shell.

---

## Before you start: ask IT for

1. **A server** (VM is fine): Ubuntu 22.04/24.04, 2 CPU, 2–4 GB RAM, the 100 GB disk. Your account must have `sudo`.
2. **A host name**, e.g. `assets.csis.pilani.bits-pilani.ac.in`, pointing at the server.
   An IP address works to start with, but **Google sign-in (later) needs a host name**.
3. **Firewall:** ports 80 and 443 open from the campus network (and SSH for you).
4. **HTTPS certificate:** either IT provides one for the host name, or the server must be
   reachable from the internet for a free Let's Encrypt certificate (step 6).
5. *(Later, for warranty emails)* SMTP details for sending mail.

---

## 1. Get the code onto the server

```bash
ssh you@server
sudo mkdir -p /srv/asset-portal
sudo git clone https://github.com/MSRishab007/BITS-CSIS-Portal.git /srv/asset-portal/app
cd /srv/asset-portal/app
```

## 2. Run the setup script

```bash
sudo bash deploy/scripts/setup.sh assets.csis.pilani.bits-pilani.ac.in
```

(Use the server's IP address instead if you don't have a host name yet.)

The script, which is safe to run again:
- installs Python, Nginx and Git
- creates the `portal` user and the folders above, with tight permissions
- creates the virtual environment and installs `requirements.txt`
- writes `.env` with a new random `SECRET_KEY` and production settings (an existing `.env` is kept)
- runs migrations (creates the database with the default categories, types and funding sources) and collects static files
- installs and starts the services: `asset-portal` (the site) and `asset-portal-backup.timer` (nightly backup at 02:30)
- installs the Nginx site and restarts Nginx

It finishes with "Done. Next:". Warnings from `check --deploy` about HSTS, SSL
redirect and secure cookies are expected until HTTPS is set up in step 6.

## 3. Create your admin account

```bash
cd /srv/asset-portal/app
sudo -u portal /srv/asset-portal/venv/bin/python manage.py createsuperuser
```

Use your `@pilani.bits-pilani.ac.in` address.

## 4. Check it works

```bash
systemctl status asset-portal --no-pager      # should say "active (running)"
curl -s -H "Host: assets.csis.pilani.bits-pilani.ac.in" http://127.0.0.1/healthz/   # {"status": "ok"}
```

Open `http://assets.csis.pilani.bits-pilani.ac.in/` in a browser and sign in.
Then go to **People** and add the HoD and faculty (paste a list with **Add many**).

## 5. Look around the settings

`/srv/asset-portal/app/.env` holds all settings. After editing it, run
`sudo systemctl restart asset-portal`.

| Setting | Meaning |
|---|---|
| `ALLOWED_HOSTS` | host name(s)/IP the site answers to, comma-separated |
| `CSRF_TRUSTED_ORIGINS` | the same, with `http://` / `https://` |
| `SECURE_COOKIES` | `True` once HTTPS works (step 6) |
| `SECURE_HSTS_SECONDS` | leave `0` until HTTPS has worked for a while; then `31536000` |
| `ALLOWED_EMAIL_DOMAINS` | only these email domains can have accounts |
| `BACKUP_KEEP_DAYS` | how many days of nightly backups to keep |
| `DEPARTMENT_NAME`, `DEPARTMENT_SHORT` | shown in the sidebar and page titles |

## 6. Turn on HTTPS

**A. Certificate from IT.** Copy the files to `/etc/ssl/asset-portal/` (`fullchain.pem`, `privkey.pem`),
then in `/etc/nginx/sites-available/asset-portal.conf` uncomment the `listen 443`, `ssl_certificate*`
and `return 301` lines.

**B. Let's Encrypt (server reachable from the internet):**

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d assets.csis.pilani.bits-pilani.ac.in --redirect
```

Then, either way:

```bash
sudo nginx -t && sudo systemctl reload nginx
sudo sed -i 's/^SECURE_COOKIES=.*/SECURE_COOKIES=True/' /srv/asset-portal/app/.env
sudo systemctl restart asset-portal
```

Open `https://…`; plain `http://` should now redirect. Re-run
`sudo -u portal /srv/asset-portal/venv/bin/python manage.py check --deploy` from the app folder:
only the HSTS warning should remain. After a couple of weeks without HTTPS problems you can
set `SECURE_HSTS_SECONDS=31536000`.

## 7. Backups

- **Automatic:** every night at 02:30 into `/srv/asset-portal/backups/`
  (`portal-backup-<date>.tar.gz`: database + all bills; 14 days kept, owner-only).
- **Now:** `sudo systemctl start asset-portal-backup`, or
  `sudo -u portal /srv/asset-portal/venv/bin/python manage.py portal_backup` from the app folder.
- **Check the timer:** `systemctl list-timers asset-portal-backup.timer`
- **Off-server copy (strongly recommended):** a backup on the same disk doesn't survive a disk failure.
  Give the `portal` user an SSH key for another machine and run nightly after the backup:

  ```bash
  sudo -u portal mkdir -p -m 700 /srv/asset-portal/.ssh
  sudo -u portal ssh-keygen -t ed25519 -N "" -f /srv/asset-portal/.ssh/id_ed25519
  sudo -u portal ssh-copy-id -i /srv/asset-portal/.ssh/id_ed25519 backupuser@10.1.2.3
  # then add to the portal user's crontab (sudo crontab -u portal -e):
  # 30 3 * * * bash /srv/asset-portal/app/deploy/scripts/offsite-copy.sh backupuser@10.1.2.3:/backups/asset-portal/
  ```

  Or ask IT to include `/srv/asset-portal/backups/` in their regular backup.

### Restoring

```bash
sudo systemctl stop asset-portal
cd /srv/asset-portal/app
sudo -u portal /srv/asset-portal/venv/bin/python manage.py portal_restore /srv/asset-portal/backups/portal-backup-2026-11-21_023000.tar.gz
sudo systemctl start asset-portal
```

The current database is kept as `db.sqlite3.before-restore-<time>` and the backup is
integrity-checked before anything is replaced.

## 8. Updating to a new version

After pushing to GitHub:

```bash
sudo bash /srv/asset-portal/app/deploy/scripts/update.sh
```

It takes a backup, pulls, installs packages, migrates, collects static files, checks the
configuration and restarts gracefully, then confirms the site answers.

## 9. Day-to-day

| Task | Command |
|---|---|
| Is it running? | `systemctl status asset-portal` |
| Live log | `journalctl -u asset-portal -f` |
| App log file | `tail -f /srv/asset-portal/logs/portal.log` |
| Nginx errors | `sudo tail -f /var/log/nginx/error.log` |
| Restart | `sudo systemctl restart asset-portal` |
| Disk space | `df -h /srv` and `du -sh /srv/asset-portal/*` |
| Locked-out user | sign in as Admin → *Technical admin* → Axes → Access attempts → delete the entry |
| Django shell | `cd /srv/asset-portal/app && sudo -u portal /srv/asset-portal/venv/bin/python manage.py shell` |

**Space:** a bill is typically 0.2–1 MB, so the 100 GB disk holds well over 50,000 bills plus
14 days of backups. Keep an eye on `df -h` once a term.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| **502 Bad Gateway** | the app isn't running: `systemctl status asset-portal`, then `journalctl -u asset-portal -n 50` |
| **400 Bad Request** | the host name isn't in `ALLOWED_HOSTS` in `.env` |
| **403 CSRF failed** on forms | the address in the browser (with `http://`/`https://`) isn't in `CSRF_TRUSTED_ORIGINS` |
| Page unstyled | static files missing: `sudo -u portal …/python manage.py collectstatic --noinput`, check the `/static/` path in the Nginx file |
| Bills give 404 for everyone | Nginx can't read `data/media`: `id www-data` must list the `portal` group, then `sudo systemctl restart nginx` |
| **413 Request Entity Too Large** | file bigger than 12 MB (`client_max_body_size` in the Nginx file) |
| `nginx -t` fails on `[::]:80` | the server has IPv6 disabled: keep the `[::]` lines commented out |
| Can't sign in after HTTPS change | `SECURE_COOKIES=True` but still browsing over `http://`: use `https://` |

## Files in `deploy/`

| File | Installed to |
|---|---|
| `gunicorn.conf.py` | used in place by the service |
| `systemd/asset-portal.service` | `/etc/systemd/system/` |
| `systemd/asset-portal-backup.service`, `.timer` | `/etc/systemd/system/` |
| `nginx/asset-portal.conf` | `/etc/nginx/sites-available/` (host name filled in) |
| `scripts/setup.sh` | first-time setup |
| `scripts/update.sh` | deploy a new version |
| `scripts/offsite-copy.sh` | copy backups to another machine |
