# DCT Odoo 19 Community add-ons

This repository contains three integrated Odoo 19 Community modules plus a
vendored, attributed OCA feature stack. Custom screens use the official DCT
navy (`#0A132B`) and electric blue (`#1577FF`), while operational Odoo screens
retain the native interface.

## Modules

- `dct_dashboard` — responsive Enterprise-style home and executive dashboard,
  backed by OCA responsive navigation, native backend dark mode, and expandable
  dialogs.
  It depends only on `web`
  and automatically shows data for Accounting, Sales, Purchase, and Inventory
  when those applications are installed and readable by the current user. It
  also provides the DCT app launcher, a persistent light/dark appearance,
  company-aware branding, and login theme while leaving Odoo's native backend
  views and navigation unchanged.
- `dct_accounting` — Odoo's native Accounting application enhanced with OCA
  financial and aged reports, VAT/tax reports, assets and depreciation, bank
  statement imports, reconciliation, partner statements, recurring entries,
  journal controls, MIS dashboards, configurable reports, and budgets. The
  add-on keeps the standard Odoo UI and organizes the additional tools inside
  the native Reporting and Configuration hierarchy.
- `dct_payroll` — a complete Community payroll application with employee
  payslips, batch runs, worked days and inputs, salary structures and rules,
  contribution registers, printable payslips, payroll journal entries,
  department analysis, and a responsive DCT payroll overview. Salary and tax
  formulas remain localization-specific and are configured through standard
  salary rules instead of being hard-coded.
- `oca_addons` — pinned Odoo 19 Community dependencies with upstream licenses,
  documentation, and source attribution. See [the vendor inventory](oca_addons/README.md).

## Installation

1. Install the Python requirements with `pip install -r requirements-oca.txt`.
2. Add both this repository and its `oca_addons` directory to Odoo's
   `addons_path`.
3. Restart Odoo and update the Apps list.
4. Upgrade or install **DCT Dashboard**, **DCT Accounting**, and **DCT
   Payroll** from Apps.

For command-line updates:

```bash
./odoo-bin \
  --addons-path=/path/to/odoo/addons,/path/to/DCT/oca_addons,/path/to/DCT \
  -d DATABASE -u dct_dashboard,dct_accounting,dct_payroll --stop-after-init
```

The DCT modules remain independently installable, but their declared OCA
dependencies are installed automatically. Online bank-provider connectors in
`oca_addons` remain optional and require provider credentials.

## Licensing

The integrated distribution is provided under AGPL-3. Every vendored OCA module
retains its own declared license, attribution, and documentation. No Odoo
Enterprise source code, assets, or branding are included.
