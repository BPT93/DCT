# DCT Odoo 19 Community add-ons

This repository contains two separately installable Odoo 19 Community modules,
styled with the official DCT navy (`#0A132B`) and electric blue (`#1577FF`).

## Modules

- `dct_dashboard` — responsive executive dashboard. It depends only on `web`
  and automatically shows data for Accounting, Sales, Purchase, and Inventory
  when those applications are installed and readable by the current user. It
  also provides the DCT app launcher, a persistent light/dark appearance,
  company-aware branding, backend palette, navbar, and login theme.
- `dct_accounting` — dedicated accounting workspace built on Odoo Community's
  `account` module, with period KPIs, cash balance, profit trend, receivable and
  payable aging, overdue invoices, recent activity, and navigation shortcuts.
  Its app menu is restricted to Accounting read-only users and above because it
  summarizes general-ledger balances. It also provides interactive Profit &
  Loss, Balance Sheet, Trial Balance, General Ledger, Partner Ledger, and
  Journal Ledger reports with drill-down plus PDF/XLSX export. Its dashboard
  uses the active company's Odoo logo and the same saved light/dark preference.

## Installation

1. Add this repository directory to Odoo's `addons_path`.
2. Restart Odoo and update the Apps list.
3. Install **DCT Dashboard** and/or **DCT Accounting** from Apps.

For command-line updates:

```bash
./odoo-bin -d DATABASE -u dct_dashboard,dct_accounting --stop-after-init
```

Each module is independent: removing one does not remove the other. The
executive dashboard also works without the accounting module installed.
