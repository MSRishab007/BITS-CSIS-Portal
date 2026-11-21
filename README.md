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
apps/accounts/     custom User model (email/username login, roles), admin
apps/catalog/      lookup lists (categories, types, vendors, funding, venues)
                   and admin-defined custom fields
apps/purchases/    invoices (Purchase) and their items (PurchaseItem)
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

## Portal screens

| URL | Screen |
|---|---|
| `/` | Dashboard: totals, recent invoices, warranties ending soon |
| `/purchases/` | Invoice list with search and filters (faculty: own; Admin/HoD: all) |
| `/purchases/new/` | Record an invoice and its items |
| `/purchases/<id>/` | Invoice details, items, change history |
| `/purchases/<id>/add-items/` | Add items to an invoice already recorded |
| `/purchases/<id>/edit/`, `/delete/` | Owner, Admin or HoD only |
| `/analytics/` | Spend by month, category, funding, vendor, faculty; warranties ending |
| `/purchases/export.xlsx` | Excel of the filtered items (button on list and analytics) |
| `/purchases/bulk/` | Bulk upload: template download, preview, import |
| `/manage/people/` | Admin/HoD: add (one or many), edit, deactivate, reset passwords |
| `/manage/lists/<kind>/` | Admin/HoD: categories & types, funding sources, venues, vendors, custom fields |
| `/purchases/<id>/bill/` | Bill file, streamed only to people allowed to see the invoice |

**Vendor box:** type to search existing vendors; pick one, or choose
*Add "…" as a new vendor*. A typed name that matches an existing vendor
(ignoring case, spaces and punctuation) uses that vendor.
**Invoice number box:** while typing, shows *your own* past invoices; picking
one opens "add items" for it. Typing a new number starts a new invoice.

**Bulk upload** (`/purchases/bulk/`): download the Excel/CSV template (built
from the current lookup lists and custom fields, with dropdowns), fill one row
per item, upload. The file is checked with a dry run (the real import inside a
transaction that is then rolled back) and errors are listed by row and column.
Only an error-free file can be imported, and the import is a single atomic transaction: every row is saved, or none is.
Admin/HoD templates have a "Faculty email or username" column for uploading
on behalf of faculty. Code: `apps/purchases/bulk.py`.

Front end: Django templates + Alpine.js (in `static/vendor/`, no build step),
styles in `static/css/app.css`, site-wide behaviour in `static/js/app.js`,
form behaviour in `static/js/purchase-form.js`.

### Design system

- Neutral base (Vercel-like), Geist font (Geist Mono for invoice/serial numbers).
- Primary colour: BITS sky blue (`--accent`, deepened to `#0B7CAD` for contrast;
  the logo blue `#5AC6E4` in dark mode). Change it in one place in `app.css`.
- BITS tri-colour in the official order — yellow · light blue · red ("innovate · achieve · lead") — as a signature: sidebar stripe, page-change
  progress bar, eyebrow marks, toast timers, avatar ring. **Red never appears alone**
  except for errors, which use their own darker red.
- Navigation: htmx "boosts" links and forms inside the app, so only `#content` (and the
  nav links) are swapped. The sidebar never reloads, its highlight slides to the new page,
  and View Transitions animate the page area. Downloads (`hx-boost="false"`), sign-out,
  technical admin and non-app responses do normal page loads.
- Motion: staggered entrances, Apple-Pay style tilt on KPI cards (`.tilt`),
  count-up numbers (`data-count`), sliding nav/segmented indicators, donut
  draw-in, page cross-fades (View Transitions). All off under "reduce motion".
- Ctrl+K (or `/`) opens the command menu: pages plus search of invoices, items,
  vendors and (for Admin/HoD) people, filtered by what the user may see.
- Logo: `static/img/bits-logo-160.png` and `-480.png`. To use an SVG, drop it in
  `static/img/` and update the two `<img>` paths in `base.html` / `login.html`.

## Data model

```
Purchase (one invoice)          PurchaseItem (one line on the invoice)
  owner ─► User                   purchase ─► Purchase
  vendor ─► Vendor                category ─► Category, item_type ─► ItemType
  invoice_number, order_number    item_name, quantity, amount
  purchase_date, delivery_date    funding_source ─► FundingSource
  bill_amount, bill_file            (+ project no. & PI for Research Grant)
  remarks, extra{custom fields}   venue ─► Venue, serial_numbers, asset_tag
                                  warranty_end_date, status, remarks, extra{}
```

- **Who sees what:** `Purchase.objects.visible_to(user)` returns everything for
  Admin/HoD and only their own invoices for faculty. Every list screen uses it.
- **Change history:** every add/edit/delete of users, lookup lists, invoices
  and items is recorded (django-simple-history) with who and when. See the
  *History* button on any admin page.
- **Custom fields:** Admin → Custom fields. Values are stored in the `extra`
  JSON column, so adding a field needs no database change.
- **Lookup lists** are deactivated, not deleted, so old records keep their values.

## Analytics & export

- Faculty see only their own figures; Admin/HoD see the department and can filter by faculty.
- Periods follow the Indian financial year (1 April – 31 March); default is the current FY.
- "Spend" = bill amounts. With a category or funding filter, item amounts are used
  instead (a bill may include other items). Category/funding charts always use item amounts.
- Charts are plain HTML/CSS (no chart library): hover or focus a bar for the exact
  amount, "Show table" for the numbers. Filters are shared with the purchase list
  (`apps/purchases/filters.py`), so the Excel export matches what's on screen.

## Management rules

- Admin and HoD use the **Manage** screens; `/admin/` is only needed for
  technical work (superusers).
- Only an Admin can create, edit or reset an Admin account or give the Admin role.
- Nobody can change their own role or deactivate themselves there.
- Lookup entries are hidden, never deleted; old records keep their values.

## Dates recorded

Every table has `created_at` and `updated_at`; users have `date_joined`.
The change history additionally stores every version with who and when.
Invoice pages show "Recorded … by …" and "Last changed … by …".

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

## Deployment

**See [DEPLOYMENT.md](DEPLOYMENT.md)** for the full step-by-step guide (Ubuntu + Nginx +
Gunicorn, HTTPS, nightly backups, updates). Short version:
`sudo bash deploy/scripts/setup.sh <host>` once, `sudo bash deploy/scripts/update.sh` for each new version.

### Deployment checklist (college server)

- `DEBUG=False`, a fresh `SECRET_KEY`, real `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`
- `SECURE_COOKIES=True` once served over HTTPS
- `python manage.py collectstatic` and `python manage.py check --deploy`
  (the HSTS and SSL-redirect warnings are expected: Nginx handles the
  redirect, and HSTS is enabled only after HTTPS is confirmed working)
- Backups: `python manage.py portal_backup` (consistent database copy + all bills in one
  archive); restore with `python manage.py portal_restore <archive>`. Never copy the
  database file while the site is running.
