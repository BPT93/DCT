# Implementation checklist

- [x] Read the complete request and inspect repository, manifests and runtime.
- [x] Target confirmed: Odoo 19 Community, local core revision `11f6e1f628b7`.
- [x] Preserve existing DCT/OCA addons and unrelated untracked files.
- [x] Phase 1: foundation, role/company/site scope, guards, sites, contracts; install.
- [x] Phase 2: planning, leave, attendance reconciliation; integration tests.
- [x] Phase 3: incidents, patrols, visits, dashboard, weekly board, map; integration tests.
- [x] Phase 4: billing, payroll worksheets, automation, reports, Arabic; upgrade.
- [x] Phase 5: regression, concurrent transactions, security, browser/report QA, documentation.

## Audit

No AGENTS.md exists in the workspace or its checked parent directories. The
repository contains dct_dashboard, dct_accounting, dct_payroll and vendored OCA
modules; their implementations are preserved. Existing dct_payroll provides
full salary-rule based payroll, so security worksheets are operational approval
and costing documents with explicit export; using both to pay the same period
requires an operator choice, and no second salary-rule engine is introduced.

The attachment includes requirements only. Reference images were not supplied.
The new interface follows the specified navy/blue direction and existing native
Odoo navigation. No production service or business database is changed.

Local WSL runtime and PostgreSQL are available. Tests used dedicated
`dct_security_test_*` databases and an isolated data directory/HTTP port.

## Evidence

Validation date: 2026-10-03. See [Validation details](docs/VALIDATION.md), including
the commands, captured screenshots, report samples and remaining limits.

- Fresh Odoo 19 Community installation: 55 backend tests passed at that stage.
- Final upgrade on the populated acceptance database: **61 tests, 0 failures,
  0 errors**. Later changes affect translation text and numeric RTL display only.
- Eight independent PostgreSQL concurrency races passed with actual separate
  cursors and fresh-transaction retries.
- Read-only installation audit: 42 menus, 26 window actions, 87 compiled view
  modes, three client actions, eight report actions and one A4 paperformat passed.
- English browser checks: 18 passed. Arabic browser checks: five passed.
- Eight PDF reports rendered in each language; all 16 pages visually reviewed.
- Arabic PO/POT catalogs validated, with no empty/fuzzy translations.
- Optional demo XML loaded explicitly in an isolated transaction and rolled back.

The acceptance database contains connected fictional customers, a two-guard site,
day/overnight shifts, replacement history, normal/late/missing/absent cases,
approved attendance and a locked period, a closed incident and patrol, a completed
visit, an approved payroll worksheet using eight approved hours, and a linked
draft customer invoice. It is separate from business databases.

Validation found and resolved real issues: Odoo 19 delegated employee creation,
transaction serialization when only child rows change, fixed-charge proration
precision, native automatic attendance for guards, financial source mutation,
stale translation templates and RTL rendering dependencies. Test-only setup and
fixture isolation errors were also corrected; final successful runs supersede
earlier failed attempts.
