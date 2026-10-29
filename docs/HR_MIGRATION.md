# Native HR and payroll — phase 3

HR dashboard, employees, manpower, recruitment, attendance, leave, payroll,
separation and HR reports now use React/strict TypeScript inside the existing
`erp.html?view=hr-…` shell. These routes request compact bootstrap and bounded APIs;
they do not fetch or save `/api/state` or `/api/hr/state` aggregates.

## Records and flows

| Register | SQL table | Flow |
| --- | --- | --- |
| Employees | `hr_employee` | Add/edit active employee; optional offered candidate and Admin-created login |
| Manpower | `hr_manpower` | Pending → Approved or Rejected |
| Candidates | `hr_candidate` | Applied → Shortlisted → Interview Scheduled → Selected → Offer Issued → Hired; rejection before hire |
| Attendance | `hr_attendance` | One employee/date entry, editable |
| Leave | `hr_leave` | Pending → Approved, Rejected or Cancelled; inclusive calendar days; no overlapping live requests |
| Payroll | `hr_payroll` | Draft → Approved → Paid; one employee/month |
| Separation | `hr_separation` | Requested → Approved → Completed, or Rejected |

Candidate manpower references are optional; linked requests must be approved. To
onboard, create an employee and select an offered candidate; that transaction marks
the candidate Hired. Direct employee creation is supported. Headcount requests are
planning records, not enforced hiring quotas.

Payroll basic pay, allowances and deductions are entered amounts. The employee
selector fills basic pay from monthly salary; the server computes net pay.
Approval posts salary expense (6100), salaries payable (2300) and deductions payable
(2310). Record Payment clears the entire net salary from 2300 against Main Bank
(1010), reconciling the liability. Existing posting-date/period-lock rules and unique
source keys apply. Approved economic values are immutable. This records payment;
it does not initiate a bank transfer. Approved/Paid payroll has authenticated,
escaped browser Print / Save as PDF payslips.

Completing an approved separation updates the employee, disables their linked
non-Admin account and revokes sessions atomically. Admin accounts require manual
account review and cannot be offboarded this way. Final settlement is an estimate
only: it creates no settlement journal/payment. Outstanding approved payroll can
still be paid after separation; new payroll requires an active employee.

Admin-only Create Login creates an account and employee link in one transaction.
Passwords are hashed in the account table, never stored in HR records, command
fingerprints or audit payloads. Existing account and reporting-manager administration
remains in User Management.

## API and access

- `GET /api/hr/records/<register>`: SQL visibility, literal search, status/employee
  filters and pagination (default 25/max 100).
- `GET /api/hr/records/<register>/<id>`: one record, version and permitted actions.
- `POST /api/hr/records/<register>` and `PATCH …/<id>`: validated create/edit.
- `POST …/<id>/actions/<action>`: explicit transitions or employee `login`.
- `GET /api/hr/employee-options/<register>`: scoped active employee choices; salary
  appears only for payroll. Other selectors search names/IDs only.
- `GET /api/hr/summary`: scoped SQL status counts and paid payroll total.
- `GET /api/hr/records/payroll/<id>/print`: payslip with export permission.
- `GET /api/hr/records/{attendance|payroll}/export`: current filtered page only,
  with export permission and spreadsheet formula escaping.

Create/actions require actor-scoped idempotency keys; edits/actions also require
current record versions. The server owns creators, transitions, net pay and account
links. Production HR aggregate PATCH returns 410. GET remains a compatibility/export
adapter. Historical regression tests explicitly enable the internal legacy write mode.

Admin and users with HR employee-edit permission (default HR Manager) have company
HR access. Other roles require explicit module/action permissions and see their
linked employee records and direct reports; manpower/candidates follow creator and
direct-manager scope. Coworkers receive no implied access. SQL filters apply before
pagination and to IDs, print, exports and mutations. Finance has no default payroll
grant. Account manager IDs determine reporting scope; employee “Reporting manager”
is descriptive text.

## Windows upgrade

Stop Flask/workers and back up your database. Replace application files, preserving
`instance` and environment/database settings. From the project folder in CMD:

```bat
.venv\Scripts\activate.bat
python -m pip install -r backend\requirements.txt
python -m flask --app backend.app init-db
python -m flask --app backend.app migrate-storage
python -m flask --app backend.app run --host 127.0.0.1 --port 5000
```

Do not reseed or recreate the administrator. Compiled frontend assets are included;
Node is only needed for frontend development. Hard-refresh the browser after upgrade.

`init-db` creates tables while preserving the existing HR aggregate. `migrate-storage`
moves all seven registers in one transaction, verifies exact round-trip and sets
`_relationalHR`. Repeated migration is a no-op. IDs, field presence/types, custom
attributes, historical labels and posted journal/source IDs are retained. Indexed
foreign keys link employees, accounts and manpower where resolvable. Old employee
labels are resolved for SQL access without rewriting historical payloads. Unresolved
references retain original metadata and null SQL links; new actions require valid
employees. Migration never replays payroll postings.

## Verification and limits

Backend scenarios cover journals, versions/idempotency, duplicates/overlap, privacy,
atomic account creation, offboarding/session revocation and rollback, recruitment,
exact migration and CSV export. The 48-view DOM suite checks navigation and native
read models. Chromium exercises real employee/login, manpower, recruitment,
attendance, leave, payroll and separation forms, printing and mobile dialogs.

Core fields use typed indexed tables; extension JSON retains historical/custom
attributes. Writes still reconstruct the HR compatibility projection and use the
shared transaction lock. Query-local validation and measured load testing remain
necessary for larger volumes. Leave accruals, attendance devices, contracts,
statutory salary tax/EOBI/social security, bank integrations and settlement accounting
are not implemented. Accounting/inventory/manufacturing/expense screen conversion
and native administration remain subsequent phases.
