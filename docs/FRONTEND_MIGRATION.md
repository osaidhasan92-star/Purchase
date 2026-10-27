# React and TypeScript migration — first vertical slice

## What runs on the new frontend

All module pages use the React workspace shell: module navigation, active submenus,
mobile menu, user dropdown and Admin-only company profile access. The existing
`erp.html?view=…` addresses, department permissions and login/session flow remain.

Customers is the first native React module, shared by CRM and Sales. It includes:

- Server-side search and 25-record pages instead of loading every customer in the browser.
- Create, edit and read-only details; details include up to 25 authorized Sales orders.
- Individual-record API writes with immutable creator metadata and per-record versions.
- Stale-edit rejection, create-request idempotency, validation and visible error states.
- Loading/empty states, keyboard Escape/focus containment in the form, and readonly permissions.
- A compact authenticated bootstrap: no full business or payroll aggregates on this route.

The module uses typed components and a typed API adapter under `frontend/src`.
TypeScript strict checks, reproducible production builds and real-browser checks run in CI.
Built frontend assets and third-party license notices are included in `frontend-dist`.

## Desktop testing: no Node installation required

Download the updated branch, keep your existing database and environment configuration,
and restart Flask as before. The ZIP includes the compiled frontend. There are no new
Python requirements, database schema changes, migrations or demo seeding steps for this update.

If you copy application files into an existing installation, include `frontend-dist`,
`frontend`, `backend/customer_api.py`, and the updated existing files. Do not overwrite
your instance database or local environment configuration.

## Frontend development

Install Node.js 22 or later and use the repository root:

```text
npm ci
npm run build:frontend
```

Start Flask separately. For incremental frontend development, keep Flask running and
run `npm run dev:frontend` in another terminal; reload the browser after recompilation.
All API calls stay on the Flask origin and use the existing HttpOnly session and CSRF
transport. Credentials and business records are not persisted in browser storage.

Other useful checks:

```text
npm run typecheck
npm run check:format
npm run test:dom
npx playwright install chromium
npm run test:browser
python -m pytest backend -q
```

On Linux, Playwright may need `npx playwright install --with-deps chromium`. CI installs
those dependencies automatically. Browser tests create an isolated temporary database,
use synthetic demo accounts and save screenshots under ignored `test-results`.
Set `PYTHON` to your virtual-environment Python executable if `python` uses another environment.

Docker now builds the frontend in a Node stage, then copies only compiled assets into
the existing Python runtime. CI rebuilds checked-in assets and rejects an outdated bundle.

## Compatibility boundary and current limits

This is a staged migration, not a claim that the entire ERP has been rewritten.
Unconverted module contents still use their existing JavaScript/HTML renderers inside
the React shell. Their inline event handlers, aggregate state loading/saving and full-page
navigation are temporary compatibility code. The boundary uses synchronous React
rendering only because those renderers bind controls immediately after rendering.
Native React components do not use that pattern for normal state updates.

Customer records still live in the existing versioned JSON aggregate so CRM/Sales and
exports remain compatible. The customer API bounds browser responses and writes one
record per request, but server filtering/sorting still operates on the aggregate in
memory. It is **not SQL pagination or a relational customer migration**. Individual
record writes advance the legacy document revision, so stale legacy writers receive a
conflict instead of overwriting new customer changes. Native compact bootstrap state
cannot be submitted through the legacy aggregate save function.

Most legacy screens still load all their authorized collections. The shell/framework
alone does not make this deployment suitable for a very large dataset or production load.

## Next conversions

1. Move customers/vendors/products into indexed relational tables with explicit migrations
   and a compatible read model for unconverted forms. Replace in-memory customer search
   with database filtering/counting/pagination.
2. Convert shared masters, CRM and purchasing screens into native components and
   resource/action APIs. Keep department policies and posted-document invariants on the server.
3. Convert Sales, HR/payroll and remaining accounting/production screens; remove their
   aggregate payloads, inline handlers and the legacy compatibility boundary.
4. Add client-side routing, organization scopes when needed, larger-data/load tests,
   accessibility checks and complete browser acceptance for documents/downloads/printing.

Each conversion must preserve the current end-to-end business simulations and access tests.
