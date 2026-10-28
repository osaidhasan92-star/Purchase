# Native Administration — phase 8

Users & Roles, Activity Log and Import / Export now use React/strict TypeScript in
the existing `erp.html?view=users`, `activities` and `admin-data` routes. They retain
the shared navigation and compact bootstrap. Routine Administration reads/actions
use bounded SQL resources and stored permission configuration; they do not rebuild
business or HR aggregates. Explicit operational import/export remains a bulk tool.

Company profile is a native React dialog in the Admin-only user dropdown across
all modules. It has no separate dashboard or settings navigation entry.

## Account demonstration

1. Administration → Users & Roles → Add User. Enter name, email, role and a password
   of 12–256 characters. Select an optional active Team manager using searchable,
   bounded choices. Salesperson/Sales Representative requires a manager.
2. Save User, then sign in through a separate browser profile to test the account.
3. Edit changes name, email, role, manager and active status. Unchecking Active user
   deactivates the account; checking it reactivates it. Editing preserves the selected
   manager unless explicitly changed. All existing sessions for that account revoke.
4. Reset Password requires matching passwords and the current record version. All
   sessions revoke. The new password is stored only as a salted password hash in
   the account table. It is never returned, audited, exported or saved in receipts.
5. Editing/resetting your own Admin account requires a fresh sign-in. The server
   blocks self-deactivation/self-demotion and manager cycles. HR separation keeps
   its existing separate authorization and session-revocation behavior.

No user deletion or new/custom-role creation is introduced. Existing configured
roles are retained, and passwords are entered only for creation or explicit reset.

## Roles, profile and audit

Select a role to change View/Create/Edit/Delete/Approve/Export grants. Unchecking
View clears the module's actions. The Admin role is fixed because Admin access is
server-owned. Saving another role revokes sessions for that role; users sign in
again to receive the changed navigation and grants. Existing business/team scope
rules continue to apply in addition to grants.

The user dropdown's Company profile edits company/legal names, address, telephone,
email and NTN/STRN. Pakistan, PKR and the existing single-company/warehouse design
remain fixed. Other company configuration, including the existing raster logo,
is preserved. Saving reloads the workspace to refresh the company header.

Activity Log reads canonical server audit rows in SQL. Admin sees all events;
other roles need Activities view permission and see only their own events, including
login events. Search matches actor name/ID or action; date filters use recorded UTC
audit dates. Details are rendered as escaped text. Audits cannot be edited/deleted.

## Import/export boundaries

Admin can explicitly export operational JSON, import an exported file up to 10 MB,
or import old demo records from the current browser's historical storage. The
migration option only reads that old storage; it does not cache current credentials
or operational records there. Credential fields are removed before import.

Existing server import validation still requires an empty operational installation.
Imported accounts stay disabled until reset/activation. Operational JSON is not a
complete restore: use a database backup for ledger, stock, manufacturing, expenses,
audit and attachments. Existing import/export endpoints and their historical format
are unchanged; roles/configuration must be reviewed rather than assuming this file
is a full system backup. Do not import demo records over a working installation.

## Native APIs

Resources are under `/api/administration`:

| Endpoint | Purpose |
| --- | --- |
| `GET /summary` | SQL account/active/Admin counts and configured role count |
| `GET /users`, `/users/<id>` | Paginated/searchable profiles or one versioned account |
| `GET /managers` | Bounded active manager choices, search and exclusion |
| `GET /roles`, `/roles/<name>` | Configured role directory and versioned permission matrix |
| `GET /company` | Admin-only company profile and version |
| `GET /activities` | SQL scoped/filterable audit events, 25 per page by default |
| `POST /commands/<kind>` | create-user, edit-user, password, role, company |

Everything except authorized own-activity reads requires the actual Admin role;
grants to Users/Settings alone do not promote someone to administrator. Lists use
SQL count/offset/limit (maximum 100). Accounts/audit remain relational; finite role
and company configuration remains in the existing stored configuration document.

Commands serialize on the shared ERP lock. Edits require current versions: missing
428, stale 409. Actor-scoped keys prevent duplicate creation/actions and conflicting
key reuse. Password fields are excluded from receipt fingerprints; credential
replay additionally verifies the submitted password against the account's current
salted hash. If it has since changed, replay returns 409 and requires a new key.
No password/hash is exposed by public account versions. Permissions are checked
before receipt replay. Configuration writes copy only stored configuration and
preserve migrated business metadata; no economic records or journals are reposted.

Session revocations, account/configuration, command receipt and audit commit together.
CSRF/origin/session protections remain unchanged. Historical account/configuration
endpoints remain compatible and do not acquire the native version contract.

## Windows upgrade

Stop the server and back up the existing `instance` directory/database. Keep your
current database, environment settings and login. Replace the application files
with the latest `codex/database-backend` branch ZIP. In CMD at the project root:

```bat
.venv\Scripts\activate.bat
python -m pip install -r backend\requirements.txt
python -m flask --app backend.app init-db
python -m flask --app backend.app migrate-storage
python -m flask --app backend.app run --host 127.0.0.1 --port 5000
```

`init-db` adds `administration_command`; existing accounts, role settings and company
profile remain in place. Repeating it does not duplicate users or repost history.
Do not reseed or recreate Admin. Built frontend assets are included; Node is not
needed for desktop testing. Open `http://127.0.0.1:5000/erp.html?view=users` and
hard-refresh the browser after upgrading.

## Verification and remaining scope

Seven new backend scenarios cover creation/password verification, credential replay,
edit/reset/deactivation session revocation, versions, validation and manager cycles,
self protection, role normalization/revocation, preserved configuration, fixed company
localization, own-activity SQL scope/pagination, compact reads/actions and repeat init.
DOM checks cover all 48 shared routes; Chromium exercises real account/manager/role
forms, reset/activation, company profile persistence, audit filters, operational
export, populated-install import rejection and a 390px mobile dialog.

The main module contents now have native screens. The overview and older CRM
company/quote registers still use compatibility contents, and trade/HR posting still
reuses some aggregate adapters internally. Query/concurrency/load and client acceptance
testing remain necessary before treating this demo as a large production ERP.
