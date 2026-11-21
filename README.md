# Asset & Purchase Portal

A department portal where faculty record equipment purchases (workstations,
gadgets, servers/GPUs, networking, research project items), with bills,
warranty tracking, funding sources, bulk Excel/CSV upload, change history
and analytics.

**Stack:** Python 3.10+ · Django 5.2 LTS · SQLite (WAL mode) · Gunicorn + Nginx

## Roles

| Role | Can see | Can manage |
|---|---|---|
| Admin | All records | Faculty, settings (categories, funding, fields…) |
| HoD | All records | Faculty, settings |
| Faculty | Own records only | Own records |

All permission decisions live in the role helpers on `apps/accounts/models.py`
(`can_view_all_records`, `can_manage_faculty`, …).

## Local setup

### Windows (PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
# If activation is blocked, run once: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt

Copy-Item .env.example .env
$key = python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
(Get-Content .env) -replace '^SECRET_KEY=.*', "SECRET_KEY=$key" | Set-Content .env

python manage.py migrate
python manage.py createsuperuser     # use your @pilani.bits-pilani.ac.in address
python manage.py runserver
```

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # then set SECRET_KEY (command is in the file)
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open http://localhost:8000/ (redirects to the admin until the portal UI is built).

Run tests: `python manage.py test`

### Applying a commit zip (review workflow)

From the repository root:

```powershell
Expand-Archive -Path "$HOME\Downloads\<zip-name>.zip" -DestinationPath . -Force
git status; git diff                 # review
git add -A; git commit -m "<message>"; git push
python manage.py migrate             # if the commit added migrations
```

## Project layout

```
config/            settings, URLs, WSGI/ASGI
apps/core/         shared pieces: TimeStampedModel base, health check
apps/accounts/     custom User model (email login, roles), admin
templates/         site-wide templates
static/            site-wide CSS/JS/images
media/             uploaded bills (private, git-ignored)
```

## Signing in & passwords

- Sign in at `/accounts/login/` with **email or username** (case doesn't matter).
  The username defaults to the part of the email before `@`.
- **Adding a user** (Admin → Users → Add): no password is typed. One is
  generated, shown **once** with Copy buttons, and the user must choose
  their own password at first sign-in.
- **Forgotten password:** select the user(s) in the list → action
  *Generate new password for selected users* → confirm.
- **Lockout:** 5 wrong passwords lock that account for 15 minutes.
  Unlock early from Admin → Axes → Access attempts (delete the entry).

## Design notes

- **Login by email, no username.** Password login works now. Google sign-in
  will be added later as a separate linked table, so the `User` table won't
  change. Accounts created without a password can't sign in until then (or
  until an admin sets one).
- **Email domain lock.** Only `ALLOWED_EMAIL_DOMAINS` (default
  `pilani.bits-pilani.ac.in`) can hold accounts. Students share this domain,
  so the faculty list maintained by Admin/HoD is the real gatekeeper:
  anyone not on it can't sign in.
- **Users are never deleted,** only deactivated, so purchase records keep
  their owner. Deletion is disabled in the admin.
- **SQLite** runs in WAL mode with a busy timeout and immediate
  transactions (see `DATABASES` in settings), which suits tens of
  concurrent users.
- **Bills are private.** `media/` is never served publicly; files will be
  streamed through a view that checks the viewer's permission.

## Deployment checklist (college server)

- `DEBUG=False`, a fresh `SECRET_KEY`, real `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`
- `SECURE_COOKIES=True` once served over HTTPS
- `python manage.py collectstatic` and `python manage.py check --deploy`
  (the HSTS and SSL-redirect warnings are expected: Nginx handles the
  redirect, and HSTS is enabled only after HTTPS is confirmed working)
- Back up `db.sqlite3` with `sqlite3 db.sqlite3 ".backup backup.sqlite3"`
  (not a plain file copy) together with the `media/` folder

Full Nginx/Gunicorn/systemd configuration will be added in a later commit.
