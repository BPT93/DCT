# DCT Payroll

`dct_payroll` turns the OCA Odoo 19 Community payroll engine into an integrated
DCT application. It adds an Enterprise-style payroll dashboard with warnings,
recent batches, employer-cost and employee-trend charts, shared payroll notes,
gross/net totals, workflow visibility, and salary-line security rules aligned
with the parent payslip.

The application navigation mirrors the familiar Enterprise workflow:
**Dashboard**, **Contracts**, **Work Entries**, **Payslips** (including **To
Pay** and **Batches**), **Reporting**, and **Configuration**. All features use
Community/OCA models and original DCT code; no Enterprise module is required at
runtime.

The module depends on the vendored `payroll` and `payroll_account` add-ons.
Install it with both the repository root and `oca_addons` on Odoo's
`addons_path`.

Payroll taxes, statutory deductions, and employer contributions differ by
country. Configure those formulas under **Payroll > Configuration > Salary
Rules**, then map posting rules to accounts on each rule's **Accounting** tab.
Use the conventional `GROSS` and `NET` rule codes so the overview and salary
analysis can identify the corresponding totals on every completed payslip.
