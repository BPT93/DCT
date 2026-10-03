# DCT Security Operations

Connected security-company operations for **Odoo 19 Community**. Install the
`dct_security_management` folder as an addon. The application includes guards,
sites/posts, effective service contracts, dated coverage slots and individual
assignments, native attendance reconciliation, patrols, incidents, inspections,
operational payroll worksheets and draft customer invoicing.

For the packaged release, extract the ZIP into your addons directory so it
contains a `dct_security_management` folder, then follow the installation steps.

## Installation and upgrade

Dependencies are the standard Community addons `web`, `mail`, `hr`,
`hr_attendance`, `hr_holidays`, and `account`. No Enterprise or paid module is
required. Python dependencies are those of Odoo 19, including pytz and dateutil.
PDF printing requires wkhtmltopdf with patched Qt and Arabic-capable fonts.
Arabic layouts also require `rtlcss` on the Odoo process's PATH. Install it with
your server's Node/npm tooling, then restart Odoo and rebuild generated asset
bundles if they were previously compiled without it. Validation used rtlcss 4.3.0.

Add the parent directory to `addons_path`, then install from Apps, or run:

```bash
python odoo-bin -c /path/to/test-or-staging.conf -d DATABASE \
  --addons-path=/path/to/odoo/addons,/path/to/DCT \
  -i dct_security_management --without-demo=all --stop-after-init

python odoo-bin -c /path/to/test-or-staging.conf -d DATABASE \
  -u dct_security_management --stop-after-init
```

Use a staging backup before upgrading a business database. Installation does not
load fictional transactions when demo loading is disabled. `demo/security_demo.xml`
is separate opt-in training data; `tools/seed_acceptance.py` refuses to run outside
a disposable `dct_security_test_*` database.

The existing DCT dashboard, accounting, payroll and OCA addons are preserved. This
addon uses `account.move` for financial documents and introduces no parallel
invoice/payment system. It can coexist with DCT/OCA payroll; choose one accounting
path for a wage period. See [Finance policies](docs/FINANCE.md) before combining
the operational worksheets with salary-rule based payslips.

## Setup

1. Assign the appropriate DCT roles below. Finance staff separately need normal
   Odoo accounting permissions for invoices or journals. No accounting or broad
   HR group is implied by an operations role.
2. Create customers, sites, posts, timezones and responsible supervisor **users**.
   Create native employees flagged as guards or operational supervisors. A guard
   needs a company-unique code and authorized sites, but no Odoo user account.
3. Add qualifications/expiry dates. Sensitive certificate files require the DCT
   HR role; native private employee fields keep their existing HR restrictions.
4. Configure company policies as an administrator. Enable automation explicitly
   per company and opt templates/contracts into their respective draft jobs.
5. Finance configures service products, taxes, income accounts, currencies and
   payment terms. Operations activates the reviewed service contract. Use separate
   effective service lines or successor contracts for later changes.
6. Set compensation and optional journal/expense/payable accounts before producing
   payroll worksheets. Accounting entries remain drafts and never mark wages paid.
7. Install Arabic in Odoo Settings and select it in user preferences for RTL.
   Set each user's timezone; shift generation uses the site's timezone.

## Role matrix

| Role | Operational scope | Write/approval powers | Financial access |
|---|---|---|---|
| Operations Manager | Allowed companies | Sites, guards, planning, contract states, incidents/patrols/visits, attendance approval, overrides | No rates, worksheets or invoices unless separately authorized |
| Site Supervisor | Assigned sites and their authorized guards | Publish roster; record real attendance; submit corrections; handle incidents, rounds and inspections | None |
| HR / Attendance Officer | Allowed companies | Guard operational data and certificates; attendance/overtime/correction/period approval | None |
| Finance Officer | Allowed companies | Contract service rates, billing review and payroll worksheets | Requires standard accounting permissions for native documents |
| Read-only operations | Allowed companies | Read records/reports; no changes | None |

The site restriction is a **global** rule for supervisors without manager/HR/finance
roles, so adding a broad native HR/attendance group does not widen their site scope.
Manager, HR and finance roles intentionally provide company-wide operational scope.
Role combinations therefore require deliberate administration. Odoo's superuser
is an explicit administrative exception.

Native employee creation in Odoo 19 requires a delegated `hr.version`. A small
bootstrap checks the DCT role, company, existing site links and a strict whitelist
of operational fields before creating that native parent. It returns immediately
to normal access rules and grants no `hr.version` ACL. Private/default salary
payloads and nested site creation are rejected. Backend overlap/leave validation
uses narrowly scoped checks on already-authorized guards so hidden conflicts do
not disappear from scheduling validation.

Attachments inherit parent-record access and field restrictions. Security
attachments cannot become public or receive public access tokens. Followers and
notification recipients must be internal users who can still read the parent.
Dashboard queries, aggregates, exports and report rendering use the same rules.
Native CSV/XLS export also requires Odoo's normal export permission.

## Workflows and policies

- [Planning, attendance and correction rules](docs/PLANNING.md): UTC intervals,
  overnight ownership, DST handling, rest overrides, replacement history, actual
  event allocation, overtime and locked periods.
- [Operations and metric definitions](docs/OPERATIONS.md): incidents, route and
  inspection snapshots, current versus selected-period cards, weekly board and map.
- [Billing and payroll formulas](docs/FINANCE.md): explicit billing bases,
  proration, approved snapshots, refunds/rebilling, compensation, currencies,
  cash versus balances, and estimated cost allocation.

Company defaults: late grace 15 minutes; suspected absence 30 minutes; minimum
rest 8 hours; maximum shift 12 hours; maximum live open attendance 16 hours;
checkout grace 2 hours; expiry reminder lead 30 days. Policies are configurable.
No incident or suspected absence automatically becomes a deduction. No process
fabricates a checkout; native automatic checkout/technical absence generation is
excluded for security guards. Native employee attendance continues for other staff.

Confirmed records are preserved. Published schedules and approved financial
snapshots cannot be rewritten by import or RPC. Row serialization plus database
uniqueness protects repeated requests; PostgreSQL serialization failures use
Odoo's normal fresh-transaction retry. Different currencies are displayed separately.

## Screens and reports

The application adds its own navy/blue OWL overview, weekly scheduling board and
site map, retaining Odoo's global navigation/theme. All cards open source records.
The weekly board opens native assignment/shift forms and exposes shortages.
There is a native calendar plus list, search, pivot and graph views.

Eight QWeb PDF actions cover site coverage, guard roster, attendance/overtime,
incidents, patrol completion, visits, payroll worksheets and contract billing.
Select dates/sites in the source lists and print the selected records. Each report
identifies its period and generation timezone/time, with the configured company
branding. Payroll/billing report execution requires finance authorization.

The site map bundles **Leaflet 1.9.4** and its BSD license. Map tiles are disabled
by default. Configure an HTTPS URL with `{z}`, `{x}`, `{y}` plus the provider's
required attribution under Company Policies. Verify the provider's terms, quotas,
privacy conditions and any API key restrictions. Browsers contact that external
provider when enabled; site-list fallback is always available. Coordinates are
fixed site coordinates, never live guard positions. No GPS, QR/NFC or biometric
evidence is asserted. See `static/lib/leaflet/LICENSE`.

## Automation

The hourly dispatcher processes only explicitly enabled companies. Individual
templates opt into draft generation and contracts opt into draft billing reviews.
It creates draft records and internal review activities; approvals remain manual.
Pending activities and generation/billing keys are idempotent. Errors identify
the model/company in server logs and savepoints isolate jobs. Qualification and
contract reminders, attendance exceptions, overdue patrols and incidents are
included. Review logs and workload batch limits before increasing company scale.

## Validation commands

The repository was inspected against local Odoo **19.0**, core revision
`11f6e1f628b7`. The supplied shell helpers default to the discovered WSL runtime;
override `ODOO_ROOT` and `ODOO_PYTHON` on another machine. They refuse business
database names and only accept `dct_security_test_*`.

```bash
bash dct_security_management/tools/run_tests.sh dct_security_test_fresh install
bash dct_security_management/tools/run_tests.sh dct_security_test_fresh upgrade
bash dct_security_management/tools/run_shell.sh dct_security_test_fresh \
  dct_security_management/tools/test_planning_concurrency.py
bash dct_security_management/tools/run_shell.sh dct_security_test_fresh \
  dct_security_management/tools/test_finance_concurrency.py
```

`tools/test_browser.cjs` tests the local acceptance server using Playwright.
`static/tests/operations_tour.js` also provides an Odoo browser tour. The acceptance
fixture and PDF renderer are explicit test-only scripts. Detailed results and
remaining limits are tracked in [Progress and evidence](PROGRESS.md).

## Scope limits

This is a backend-only Community application. It includes no mobile app, portal,
tracking integration, authentication API or payment transfer. Payroll worksheets
are operational calculations and approvals, not country-certified statutory
payroll. Statutory taxes/contributions require a compatible localization.
Retrospective locked work uses explicit reviewed adjustments/credit workflows;
there is no automatic recalculation of previously posted business records.

Ambiguous/nonexistent DST template boundaries need an explicit intended UTC shift.
Effective compensation changes require split worksheet periods. The weekly board
shows at most 150 guards and 1,000 assignments with a visible truncation warning;
use site filters for larger rosters. Maps depend on the configured provider and
network; the site list is usable without either. External providers and production
deployment were not part of validation. Reference images were not in the supplied
attachment; the design follows the written brief.

License: AGPL-3; bundled Leaflet retains its BSD license and attribution.
