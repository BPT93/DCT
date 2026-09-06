# Vendored OCA add-ons for Odoo 19

These unmodified add-on directories are vendored from the Odoo Community
Association (OCA) `19.0` branches so this repository can provide an
Enterprise-like feature set on Odoo Community without copying Odoo Enterprise
code or branding.

## Enabled by the DCT modules

- Native responsive application navigation, dark mode, and expandable dialogs
- General ledger, journal ledger, trial balance, open-items, aged-partner, VAT,
  tax-balance, and partner-statement reporting
- Asset profiles, depreciation boards, disposal, and asset reporting
- Bank statements, file imports, and Community reconciliation
- MIS dashboards, configurable KPI reports, comparisons, PDF/XLSX exports, and
  budgets
- Chart updates, recurring journal-entry templates, journal lock dates, posting
  metadata, and Accounting usability menus

Online bank connectors are included but are not installed automatically because
each provider requires its own account, credentials, and service terms.

## Upstream snapshots

| Repository | Commit |
| --- | --- |
| `OCA/account-financial-reporting` | `fc820306102ef3ad855fa23c73057bbcd588c16a` |
| `OCA/account-financial-tools` | `f553f7642ab8ab8b73917bcb5a7361f8a560e0e6` |
| `OCA/account-reconcile` | `111955e97014433215e94387caa72dd7f534c6d4` |
| `OCA/bank-statement-import` | `65316c38d7a5586456bc751d8939b84f1cf0bc2e` |
| `OCA/mis-builder` | `58a237a5dc85c06a911b87ea4cfca8175ad4a78a` |
| `OCA/reporting-engine` | `b730d603317691d9608a8a3c5710286d9dbc81f1` |
| `OCA/server-ux` | `8e5120600987969156c2a59c1ad86bec37318966` |
| `OCA/web` | `8ac7fdbf692f16c98dfcc626e01d37c66124ef1b` |

Every copied module retains its upstream authorship, copyright headers,
manifest license, documentation, and source files. Repository license texts are
stored in [`licenses`](licenses/). Most modules are AGPL-3; several dependencies
are LGPL-3 as declared in their manifests.

## Deployment

Add both the repository root and `oca_addons` to Odoo's `addons_path`:

```ini
addons_path = /path/to/odoo/addons,/path/to/DCT/oca_addons,/path/to/DCT
```

Required Python packages:

```bash
pip install -r /path/to/DCT/requirements-oca.txt
```
