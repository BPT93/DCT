# Contract billing and payroll worksheets

## Native integrations and access

Security billing creates standard `account.move` customer invoices. Payroll accounting creates standard draft miscellaneous journal entries. Posting, reconciliation, credit notes, payments, and accounting reports remain native Odoo workflows.

Assign the DCT Finance Officer role to finance staff. Invoice or journal creation also requires the appropriate native Odoo accounting role. DCT does not grant an operations manager accounting permissions. Operations managers activate contracts; finance officers configure service rates, approve billing, and approve worksheets. Contract currency and operational coverage are visible to operations; rates, configured accounts, and taxes are restricted to finance.

The repository already contains `dct_payroll` and OCA `payroll` / `payroll_account`, using the Odoo 19 `hr.version` model. This addon deliberately does not depend on those modules or replace their statutory salary structures and payslips. Its compensation table supplies basic operational estimates and attendance provenance. If the existing payroll system is used to account wages, export/reconcile the worksheet there and **do not create the optional worksheet journal entry**. No automatic payslip bridge, statutory tax calculation, contribution calculation, bank transfer, or paid-wage claim is implemented.

## Contract setup

1. Create the customer, sites, and posts in the same company.
2. Create a dated contract and select its sites and currency.
3. Finance adds effective-dated service lines with products, quantity, rate, coverage requirements, and an explicit billing basis. Select sales taxes deliberately; no fixed tax rate is supplied. An income account may be set on the service line or inherited from the configured product/category.
4. Set the billing cycle and payment terms, then have an operations manager activate the contract.

Contract dates and service line dates are inclusive. Activation locks customer, company, currency, dates, cycle, and payment terms. Activated service lines remain immutable. Add a non-overlapping future line or a successor contract for later changes. A service line must fit within its contract dates and reference one of its sites. The same site/post/product/basis cannot have overlapping effective lines.

## Billing bases and formulas

Every line names its billing basis. Different service lines can intentionally represent different services; the system does not infer or blend their quantity formulas.

- **Fixed period:** `rate × configured units × calendar-cycle fraction`. The fraction is the sum of `covered calendar days / days in that month / months per cycle`. Monthly, quarterly, and annual cycles contain 1, 3, and 12 months. With Whole Calendar Cycles Only, the period must start and end on complete calendar-cycle boundaries.
- **Required guard shifts:** `rate × configured multiplier × sum(required guards on published shift slots)`. Slots are selected by the shift's local start date, so an overnight slot belongs to its starting date. This charges configured coverage, including uncovered required positions; it does not imply those hours were worked. Use Approved Actual Hours when the contract bills delivered time.
- **Approved actual hours:** `rate × approved allocated hours intersecting the service period`. Site-local midnight boundaries are converted to UTC, including 23- and 25-hour daylight-saving days. An allocation crossing a billing boundary is split proportionally by its actual interval. Draft allocations and open attendance never contribute.

Discounts apply uniformly as a percentage of the service lines. A fixed service deduction uses a configured product and its configured taxes/account. Both require a recorded approval reason. The displayed review total is an untaxed estimate; native invoices calculate taxes and rounding.

The calculation stores site, period, basis, product, taxes, account, quantity, rate, and approved allocation links. Approved quantities keep their full precision. Each native invoice line represents one service charge with the currency-rounded approved subtotal as its price; its description and linked snapshot show the original approved quantity and rate. This prevents native Product Unit decimal precision from turning `15/31 × 3100` into an incorrect invoice. Configured fixed taxes apply once per service charge line. Tax-inclusive or tax-exclusive interpretation follows the configured native tax, and the displayed untaxed estimate uses that same native calculation. Discounts are rounded per line. The invoice's untaxed amount is checked against the approved estimate; inadequate Product Price precision blocks creation until corrected. Core accounting fields remain native. Economic values on the generated original invoice are frozen; corrections use cancellation/credit and a new approved source review.

## Billing workflow and corrections

Create a draft review for an explicit period, Calculate, Approve, and Create Invoice. Invoice creation remains a draft and is idempotent. Approval reserves that contract period. Partially overlapping approvals are rejected, while adjacent or distinct partial periods are permitted. Actual-hour quantities also cannot be reused by overlapping service lines or contracts.

To release a period for rebilling, record a cancellation reason and either cancel the draft invoice in Accounting or post credit notes totaling exactly the original invoice amount in the same currency. Partial credits retain the period reservation. Credit notes retain their source billing link. Once the billing period is released, the source invoice and release credit documents cannot be reopened, cancelled, or reversed again: doing so could restore an old charge after replacement billing. This workflow does not automatically unreconcile payments, issue refunds, or post a new invoice.

Company automation and the contract's draft billing policy must both be enabled for automatic prior-month draft review creation. Retries do not create another overlapping draft. The job does not approve reviews or create/post invoices, and records batch failures in the Odoo log.

## Compensation and worksheet formulas

Set effective compensation for each guard, company, and currency. Periods cannot overlap. A worksheet must fit entirely within one compensation record; split it at a compensation rate change. Compensation used by an approved worksheet is locked. Finance may complete only the optional accounting journal/account setup until the first linked journal entry has been created; this never changes approved quantities or pay rates.

- **Hourly regular amount:** `hourly rate × (approved worked hours − allocated approved overtime hours)`.
- **Monthly regular amount:** `monthly rate × calendar-month fraction`. This remains an estimate even with no approved attendance; no automatic absence or leave deduction is made.
- **Overtime:** `explicit overtime rate × approved assignment overtime allocated to the worksheet period`. Allocation uses each included attendance segment's share of its assignment's approved hours. Native attendance overtime is not added again.
- **Allowance:** `monthly allowance × calendar-month fraction + explicit additional allowance`.
- **Net:** `regular amount + overtime + allowance − approved deduction + signed prior-period adjustment`.

The configured monthly hour divisor documents the monthly rate's estimated hourly cost (`monthly rate / divisor`); it does not replace the explicit overtime rate or change monthly calendar proration. Base cost is allocated to sites in proportion to approved worked hours. With no worked hours it remains an unallocated estimate. Overtime, allowances, deductions, and adjustments remain separately identifiable worksheet lines.

Explicit allowances, deductions, and adjustments require a reason. A prior-period adjustment must link to an earlier approved worksheet for the same guard. Incidents, suspected absence, and leave never generate fines or deductions. Only validated leave source IDs are retained for review provenance; finance access does not grant medical descriptions or leave documents.

## Approval, export, and optional accounting

Draft → Reviewed → Approved → Exported/Accounted. A review can return to Draft before approval. Approval recalculates under a transaction lock and freezes the snapshot. Repeated approval/export/entry actions are safe. A later correction belongs in a subsequent period as an explicit adjustment; confirmed history is retained.

CSV export contains the period, guard, currency, approved breakdown, and an explicit statement that approval is not proof of payment. The PDF report is provided by the addon report module. Native pivots aggregate hours; monetary fields do not offer unsafe cross-currency totals. Compare monetary figures within one currency or use native accounting currency conversion.

Optional accounting requires a miscellaneous journal plus expense and payable/accrual accounts on the effective compensation record. The entry debits estimated net guard cost and credits the configured accrual, with the employee's work contact as partner. Foreign-currency amounts are converted by native Odoo rates at period end and retain their original currency amount. This basic accrual does not split statutory withholding liabilities; use the existing payroll implementation when such posting is required. Missing configuration blocks entry creation. Creating or approving the worksheet does not mark wages as paid.

## Concurrency and tests

### Dashboard financial definitions

Financial cards query permission-filtered native records and keep currencies separate. Net invoiced revenue is posted invoice untaxed value less posted credit-note untaxed value for the selected invoice-date period. Outstanding is the current signed residual of that same invoice cohort; it is not a historical aged-receivables reconstruction.

Cash received uses actual receivable partial reconciliations with posted bank-statement entries or native payments marked as matched/settled. It is dated by the settlement journal entry, includes settlements of earlier invoices, and subtracts outbound refund payments. Credit-note offsets, miscellaneous write-offs, currency-difference entries, and unsettled payments do not count as cash. A partially bank-matched payment is conservatively excluded until native Odoo marks the payment settled. Source journal entries have their own drilldown.

Estimated guard cost includes approved/exported/accounted worksheets overlapping the selected period, prorated evenly by included calendar days. Site filtering allocates invoice deductions and payment balances in proportion to source service subtotals, and allocates total worksheet costs in proportion to its site base-compensation lines. These site and partial-period allocations are estimates; unallocated monthly costs are visible at company level. Estimated margin is net invoiced revenue minus estimated guard cost within each currency. It excludes overhead, other accounting expenses, and statutory payroll items and is not actual profit. Currency buckets with only costs or only revenue remain separate.

Billing serializes on contract and approved allocation rows; payroll serializes on the employee row. Odoo uses PostgreSQL Repeatable Read. The lock helpers touch the common serialization row so concurrent stale snapshots raise a serialization failure; normal Odoo transaction retries then recheck the overlap. This matters because a row lock alone does not refresh a Repeatable Read snapshot.

`tests/test_finance.py` covers workflow/RPC guards, invoice snapshots and idempotence, partial periods, cancellation/rebilling, full and partial posted credits, approved overnight hours, cross-contract actual-hour reuse, payroll freezes, supervisor/HR/manager access denial, account/source forgery, missing accounting setup and its repair, effective-rate splits, explicit deduction approval, native currency conversion, and DST boundaries. `tools/test_finance_concurrency.py` performs four races with separate committed cursors: overlapping billing approvals, repeated invoice creation, overlapping payroll creation, and repeated journal creation. It refuses database names outside `dct_security_test_*` and leaves fictional fixtures only in that disposable test database. Runtime results belong in the root README/test report; the presence of tests is not a claim they passed.
