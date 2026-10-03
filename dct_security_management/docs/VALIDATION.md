# Validation evidence

Validated on 2026-10-03 against Odoo 19 Community, source revision
`11f6e1f628b7`, using PostgreSQL in WSL Ubuntu. All writes were restricted to
dedicated `dct_security_test_*` databases. No business database, existing DCT/OCA
addon or production service was changed.

## Results

| Check | Actual result |
|---|---|
| Fresh install, without demo | Installed successfully; 55 backend tests passed at that stage |
| Final upgrade with populated acceptance data | 61 backend tests; 0 failures, 0 errors |
| Planning concurrency | 4 independent-cursor races passed |
| Financial concurrency | 4 independent-cursor races passed |
| Menus and window actions | 42 menus, 26 actions, 87 view modes compiled successfully |
| Client actions and reports | 3 client actions, 8 report actions/templates/helpers, 1 A4 paperformat resolved |
| English browser | 18 checks passed; no JavaScript or asset errors |
| Arabic browser | 5 checks passed; real RTL dashboard, board, calendar, map fallback and financial forms |
| PDF rendering | All 8 reports in English and Arabic; 16 one-page samples visually reviewed |
| Arabic catalog | PO/POT synchronized; no empty, fuzzy or placeholder errors |
| Optional demo data | Explicit XML load verified and rolled back |
| Static source/package checks | Python/XML parsing, JavaScript syntax and manifest paths validated |

The concurrency checks use separate PostgreSQL cursors. They cover competing
overlapping assignments/attendance allocations/billing/payroll, repeated roster
generation, publication racing with a new assignment, repeated invoice creation
and repeated payroll journal creation. A losing transaction retries against fresh
state. The resulting records and identifiers are asserted after both workers finish.

Backend tests include overnight and DST boundaries, approved leave conflicts,
replacement history, partial attendance, corrections and locks, native guard
auto-checkout exclusion, effective rates, refunds/rebilling, immutable approved
sources, missing financial configuration and cron opt-in/idempotency. Access tests
exercise two companies, two site supervisors, combined native HR groups, direct
model calls, exports, attachments, followers, dashboard aggregates and reports.

## Runtime and visual checks

Browser tests used Playwright with Microsoft Edge against the local Odoo server.
The English pass covers filters, source drill-downs, weekly planning, calendar,
map fallback and ten native record list/form screens. The configured-map check
aborts tile requests in the test browser, verifies site pins/attribution/fallback,
and restores the original company map configuration. No real tile provider was
contacted.

Arabic checking uses Odoo's `ar_001` language and an isolated reviewer account.
The server needs **rtlcss** on its PATH; version 4.3.0 was used. A stale POT file
was corrected so newly added translated terms are available to Odoo's loader.
Numeric weekly date/time ranges use explicit left-to-right direction inside the
otherwise right-to-left board.

PDFs were produced by the installed QWeb report actions and wkhtmltopdf
0.12.6.1 with patched Qt, then rendered using Poppler for inspection. The patched
binary was extracted under the isolated validation directory; no system package
was replaced. The reports use the actual configured company logo. The disposable
database still has Odoo's default logo and company name; no branding was invented.

Captured screenshots are in `docs/screenshots/`. They show the running system and
fictional acceptance records. Sample PDFs are in `docs/sample_reports/`.

## Reproducing the checks

Follow the install/upgrade commands and runtime overrides in the README. The test
helpers enforce the `dct_security_test_*` database prefix. Run these from the
directory containing the addon:

```bash
bash dct_security_management/tools/run_tests.sh dct_security_test_review install
bash dct_security_management/tools/run_tests.sh dct_security_test_review upgrade
bash dct_security_management/tools/run_shell.sh dct_security_test_review \
  dct_security_management/tools/check_installation.py
bash dct_security_management/tools/run_shell.sh dct_security_test_review \
  dct_security_management/tools/test_planning_concurrency.py
bash dct_security_management/tools/run_shell.sh dct_security_test_review \
  dct_security_management/tools/test_finance_concurrency.py
```

The browser runner accepts `DCT_TEST_URL`, `DCT_DB`, `DCT_LOGIN`, `DCT_TEST_PASSWORD`
and `DCT_ARABIC` environment settings; inspect its header for local runtime paths.
`seed_acceptance.py` creates the explicit fictional workflow. `load_arabic.py`
installs language data, and `render_acceptance_reports.py` prints its actual records.
Supply patched wkhtmltopdf and rtlcss on both the server and rendering shell PATH.
The render helper expects the local test server on port 18080.

Raw logs and captures remain locally under `.validation/` and
`/home/mustafa/.local/share/dct-security-validation/`. The ZIP excludes local
database files, caches and raw logs. Compact result evidence is included under
`docs/evidence/`. `tools/package_addon.py` validates source files
and builds the ZIP and SHA-256 file in the parent `dist/` directory.

## Limits of this evidence

The checks establish local installation, business workflow, access, concurrency
and browser/report behavior for the tested scenarios. Production deployment,
external map-provider service, large-roster load testing and every third-party
addon combination were not tested. The existing full payroll addon was preserved;
choose one posting path per pay period to avoid paying twice. These operational
worksheets require a suitable localization for statutory payroll.
The included native Odoo tour was not separately executed; frontend acceptance
used the Playwright smoke runner described above.

Only the written brief was supplied; matching unavailable reference images could
not be verified. See the README and workflow documents for explicit policy choices.
