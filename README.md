# Purchase — database-backed ERP

This branch converts the browser demo into a shared, single-company application.
It preserves the existing purchasing, CRM, sales and HR interfaces while moving
their records to a Flask API and a database. PostgreSQL is the deployment target;
SQLite is available for local development and automated tests.

## Included

- Shared purchasing, CRM, sales, company settings and HR/payroll storage.
- Hashed passwords; opaque, database-backed eight-hour login sessions; HttpOnly
  and SameSite cookies; CSRF validation; persistent failed-login throttling.
- Server-owned role permissions, separate HR permissions, sales-team filtering,
  account administration, and session revocation after password/account changes.
- Version-checked saves: an outdated browser gets HTTP 409 instead of overwriting
  another user's changes. The UI waits for server saves before reporting success.
- Protected PDF attachment upload/download for requests, vendor quotations and
  direct purchase orders (10 MB maximum per PDF). Attachments are in the database.
- Server-generated audit events, admin data export, and one-time browser-data import.
- Docker/PostgreSQL deployment configuration, API tests and DOM workflow checks.
- CRM script loading/synchronization fixes, consistent discounted-tax calculations,
  separate purchasing/sales balance helpers, and server validation for document
  numbers, overpayments, receipt quantities and sales-order dispatch limits.

## Local setup (Python 3.12)

Run from the repository root:

```bash
python -m venv .venv
```

Activate `.venv` (`.venv\Scripts\activate` on Windows, `source .venv/bin/activate`
on Linux/macOS), then:

```bash
python -m pip install -r backend/requirements.txt
python -m flask --app backend.app init-db
python -m flask --app backend.app create-admin
```

The administrator command prompts for name, email and a password of at least
12 characters. There are no default login credentials. `init-db` preserves
existing data and must run before starting workers.

For local HTTP development, disable the HTTPS-only cookie explicitly:

```bash
# Linux/macOS
COOKIE_SECURE=false python -m flask --app backend.app run --port 8000
```

```powershell
# Windows PowerShell
$env:COOKIE_SECURE="false"
python -m flask --app backend.app run --port 8000
```

Open `http://127.0.0.1:8000` and log in with the administrator you created.
The SQLite file is `instance/purchase.sqlite`; it must not be committed.
Do not use Flask's development server for a client deployment.

## VPS deployment with PostgreSQL and Docker Compose

One installation serves one company. Use a separate deployment and database for
each client; this version does not implement multi-tenant company isolation.

1. Copy `.env.example` to `.env`.
2. Generate a strong hex database password, for example with
   `python -c "import secrets; print(secrets.token_hex(32))"`, and set
   `POSTGRES_PASSWORD`. Hex avoids URL-escaping problems in `DATABASE_URL`.
3. Set `PUBLIC_ORIGIN` to the exact HTTPS origin, such as
   `https://erp.example.com` (no path). Keep `.env` private.
4. Initialize and create an administrator:

```bash
docker compose build
docker compose up -d db
docker compose run --rm web flask --app backend.app init-db
docker compose run --rm web flask --app backend.app create-admin
docker compose up -d web
```

5. Point your existing HTTPS reverse proxy at `127.0.0.1:8080`.
   `deploy/nginx.conf.example` contains the location block. Configure the domain
   and TLS certificate in your proxy. PostgreSQL is not exposed on a host port.
6. Verify sign-in, an actual save, a second browser reading the saved record,
   restricted-role access, and a backup/restore drill before client handover.

The database uses the named `purchase_db` volume. **Do not run
`docker compose down -v` unless you intend to erase the database.** A container
restart or ordinary `docker compose down` does not delete this named volume.

For a managed database instead of Compose, set `DATABASE_URL` to a PostgreSQL
connection URL. Both `postgresql://` and `postgresql+psycopg://` are supported.
Use the database provider's TLS settings when the connection crosses networks.

## Moving existing browser demo records

The database starts empty; browser data is never uploaded automatically.

As administrator, open **Import / Export Records** in the sidebar
(`admin-data.html`). On the same origin/browser as the previous demo, choose
**Import this browser's demo records**. Otherwise export from the old origin
using its browser console, then choose the resulting JSON file on the import page:

```js
const data = {
  app: JSON.parse(localStorage.getItem('purchase_demo_state_v1') || '{}'),
  hr: JSON.parse(localStorage.getItem('unified_hr_payroll_v1') || '{}')
};
const url = URL.createObjectURL(new Blob([JSON.stringify(data)], {type:'application/json'}));
const a = document.createElement('a');
a.href = url; a.download = 'purchase-demo-records.json'; a.click();
setTimeout(() => URL.revokeObjectURL(url), 1000);
```

Import is administrator-only and works only while both business and HR registers
are empty. Browser account passwords and role definitions are not trusted or
imported. Existing referenced user IDs are retained as **disabled accounts with
random password hashes**. Reset their passwords and activate them through User
Management. The first administrator retains ID `demo-admin` for compatibility
with existing ownership references. Review imported manager assignments.

Old attachments that contained only filenames cannot be recovered; upload the
actual PDFs. Invalid/duplicate legacy business records must be corrected before
import. An import is not a database backup restore.

## Backups and restore

The admin JSON export contains business/HR records and sanitized user profiles.
It does **not** include password hashes, login sessions, audit history or PDF
contents. Use PostgreSQL backups for a full recovery:

```bash
mkdir -p backups
docker compose exec -T db pg_dump -U purchase -d purchase -Fc > backups/purchase.dump
```

Copy backups to private off-server storage. To restore into a deliberately chosen
empty/recovery database, stop the web service and run:

```bash
docker compose stop web
docker compose exec -T db pg_restore -U purchase -d purchase --clean --if-exists < backups/purchase.dump
docker compose up -d web
```

`--clean` replaces database objects. Verify the target and take a fresh backup
before restoring over an existing installation. Restores include sessions;
invalidate restored sessions before reopening to clients:

```bash
docker compose exec -T db psql -U purchase -d purchase -c 'DELETE FROM login_session;'
```

For SQLite development, stop the application before copying the database file.

## API

All paths below are prefixed with `/api`. Mutating authenticated requests require
the `X-CSRF-Token` returned by login or `/auth/me`; the browser sends the opaque
session cookie automatically. No tokens or credentials are stored in LocalStorage.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/auth/login` | Sign in and issue session cookie |
| GET | `/auth/me` | Current profile and CSRF token |
| POST | `/auth/logout` | Revoke current session |
| POST | `/auth/change-password` | Change password and revoke all user sessions |
| GET | `/state` | Permission-filtered business records and revision |
| PATCH | `/state` | Save changed collections with expected revision |
| GET/PATCH | `/hr/state` | Permission-filtered HR records / versioned HR save |
| GET/POST | `/users` | Administrator user listing / creation |
| PUT | `/users/:id` | Administrator account update |
| POST | `/users/:id/password` | Administrator reset, revoking sessions |
| POST | `/attachments` | Multipart PDF and `module` upload |
| GET | `/attachments/:id` | Permission-checked PDF download |
| GET | `/admin/export` | Administrator records export |
| POST | `/admin/import` | One-time import into empty registers |
| GET | `/admin/audit?before=123` | Administrator audit pagination |
| GET | `/health` | Database connectivity probe |

Save body example: `{"revision":3,"changes":{"vendors":[...]}}`.
Return codes include 401 (sign in), 403 (permission/CSRF), 409 (stale revision),
428 (revision missing), and 429 (failed-login limit).

If a save fails, the red **NOT SAVED** notice blocks normal navigation. Reloading
server records discards the unsaved local edits. Re-enter those edits after
reloading. There is intentionally no automatic retry of stale business data.

## Tests

```bash
python -m pip install pytest
python -m pytest backend -q
npm ci
npm run test:dom
```

The DOM test starts its own HTTP server and isolated temporary SQLite database.
It exercises page scripts and actual saves; it is not a real-browser visual test.
GitHub Actions runs both the API tests and frontend syntax checks.

## Implementation boundaries and remaining work

This is a backend conversion of the current workflows, not a claim that every ERP
business rule is complete. Accounts, sessions, audit events and attachments have
dedicated tables. Business records currently use two versioned JSON database
aggregates (`app` and `hr`) to preserve the existing UI. This is durable shared
storage, but large installations should move to normalized document/line tables,
database-generated document sequences and granular transaction APIs. Unrelated
edits within the same aggregate can intentionally conflict.

- Full general-ledger accounting, bank reconciliation, payment-gateway execution,
  tax-country compliance and statutory payroll calculations are not implemented.
- Purchase matching still follows the existing full-receipt/full-PO policy;
  partial billing and landed-cost allocation need a dedicated redesign.
- Delivery quantities are bounded by order quantity; a proper warehouse/stock
  ledger, service-vs-stock product types, reservations, returns and valuation remain.
- Some legacy order/receipt lines still reference product IDs or array position
  instead of immutable line IDs. HR history still uses legacy employee labels.
- RFQ/quotation “Send” records a workflow status. SMTP delivery is not configured.
- Separation still requires review of the linked login account in User Management.
- Import/export is administrative; there is no self-service multi-company tenancy.
- PDF signatures are checked, but uploads are not malware-scanned. Serve PDFs as
  downloads. A real-browser security/visual review and PostgreSQL deployment smoke
  test are required before production acceptance.
- Initial schema creation uses `init-db`. Future schema changes need versioned
  database migrations; `init-db` is not an upgrade/migration engine.

The authentication cookie settings follow Flask's security guidance:
https://flask.palletsprojects.com/en/stable/web-security/
