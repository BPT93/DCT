import base64
import csv
import io
from datetime import datetime, time, timedelta

import pytz
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, Command, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import SQL


_FINANCE_TOKEN = object()
_FROZEN_PAY = ('approved', 'exported', 'accounted')


def _employee_lock(records):
    records.check_access('read')
    records.flush_recordset()
    if records:
        records.env.cr.execute('SELECT id FROM hr_employee WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(records.ids))])
        # Odoo uses REPEATABLE READ: touching the serialization row forces a
        # waiting concurrent transaction to retry with a fresh snapshot.
        records.env.cr.execute('UPDATE hr_employee SET write_date = clock_timestamp() WHERE id IN %s', [tuple(sorted(records.ids))])
        records.invalidate_recordset()


def _allocation_lock(records):
    records.check_access('read')
    records.flush_recordset()
    if records:
        records.env.cr.execute(SQL('SELECT id FROM %s WHERE id IN %s ORDER BY id FOR UPDATE', SQL.identifier(records._table), tuple(sorted(records.ids))))
        records.env.cr.execute(SQL('UPDATE %s SET write_date = clock_timestamp() WHERE id IN %s', SQL.identifier(records._table), tuple(sorted(records.ids))))
        records.invalidate_recordset()


def _utc_bounds(site, first, last):
    tz = pytz.timezone(site.tz or 'UTC')
    # Local calendar periods are half-open, including the whole final date.
    return (tz.localize(datetime.combine(first, time.min)).astimezone(pytz.UTC).replace(tzinfo=None),
            tz.localize(datetime.combine(last + timedelta(days=1), time.min)).astimezone(pytz.UTC).replace(tzinfo=None))


def _calendar_fraction(first, last, cycle_months=1):
    total = 0.0
    current = first
    while current <= last:
        next_month = current.replace(day=1) + relativedelta(months=1)
        segment_end = min(last + timedelta(days=1), next_month)
        total += (segment_end - current).days / (next_month - current.replace(day=1)).days / cycle_months
        current = segment_end
    return total


class SecurityBilling(models.Model):
    _name = 'dct.security.billing'
    _description = 'Security Billing Review'
    _inherit = ['dct.security.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'
    _rec_name = 'name'

    name = fields.Char(compute='_compute_name', store=True)
    contract_id = fields.Many2one('dct.security.contract', required=True, check_company=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='contract_id.company_id', store=True)
    partner_id = fields.Many2one(related='contract_id.partner_id', store=True)
    currency_id = fields.Many2one(related='contract_id.currency_id', store=True)
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    state = fields.Selection([('draft', 'Draft'), ('approved', 'Approved'), ('invoiced', 'Invoiced'), ('cancelled', 'Cancelled')], required=True, default='draft', tracking=True, copy=False)
    line_ids = fields.One2many('dct.security.billing.line', 'billing_id', copy=False)
    amount_total = fields.Monetary(compute='_compute_total', store=True, aggregator=False)
    discount_percent = fields.Float(help='Explicit approval applies this discount to every service line.')
    deduction_amount = fields.Monetary(aggregator=False, help='Explicit service deduction; approval requires a reason and a configured deduction product.')
    adjustment_reason = fields.Text()
    deduction_product_id = fields.Many2one('product.product', check_company=True)
    deduction_account_id = fields.Many2one('account.account', readonly=True, copy=False, check_company=True)
    deduction_tax_ids = fields.Many2many('account.tax', readonly=True, copy=False, check_company=True)
    invoice_id = fields.Many2one('account.move', readonly=True, copy=False, check_company=True, ondelete='restrict')
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    cancellation_reason = fields.Text()

    @api.depends('contract_id.name', 'date_start', 'date_end')
    def _compute_name(self):
        for rec in self:
            rec.name = '%s / %s - %s' % (rec.contract_id.name or '', rec.date_start or '', rec.date_end or '')

    @api.depends('line_ids.subtotal', 'line_ids.tax_ids', 'discount_percent', 'deduction_amount', 'deduction_tax_ids')
    def _compute_total(self):
        for rec in self:
            service_amount = sum(line.tax_ids.compute_all(line.subtotal * (1 - rec.discount_percent / 100),
                currency=rec.currency_id, quantity=1, product=line.product_id, partner=rec.partner_id)['total_excluded'] for line in rec.line_ids)
            deduction = rec.deduction_tax_ids.compute_all(-rec.deduction_amount, currency=rec.currency_id, quantity=1,
                product=rec.deduction_product_id, partner=rec.partner_id)['total_excluded'] if rec.deduction_amount else 0
            rec.amount_total = service_amount + deduction

    @api.model_create_multi
    def create(self, vals_list):
        self._check_role('group_finance')
        forbidden = {'line_ids', 'invoice_id', 'approved_by', 'approved_at', 'deduction_account_id', 'deduction_tax_ids'}
        if any(v.get('state', 'draft') != 'draft' or forbidden.intersection(v) for v in vals_list):
            raise AccessError(_('Create a draft review, then use its workflow actions.'))
        return super().create(vals_list)

    def write(self, vals):
        self._check_role('group_finance')
        if {'state', 'invoice_id', 'approved_by', 'approved_at', 'line_ids', 'deduction_account_id', 'deduction_tax_ids'}.intersection(vals):
            raise AccessError(_('Billing snapshots and workflow fields are controlled by actions.'))
        allowed = {'cancellation_reason', 'message_follower_ids', 'activity_ids', 'message_ids'}
        if set(vals) - allowed and any(r.state != 'draft' for r in self):
            raise UserError(_('Approved billing is locked. Cancel through the controlled workflow before rebilling.'))
        return super().write(vals)

    def unlink(self):
        if any(r.state != 'draft' for r in self):
            raise UserError(_('Billing history must be retained.'))
        self.line_ids.with_context(_dct_finance_token=_FINANCE_TOKEN).unlink()
        return super().unlink()

    @api.constrains('contract_id', 'date_start', 'date_end', 'discount_percent', 'deduction_amount')
    def _check_period(self):
        for rec in self:
            if not rec.contract_id.date_start <= rec.date_start <= rec.date_end <= rec.contract_id.date_end:
                raise ValidationError(_('The billing period must lie within the contract.'))
            if not 0 <= rec.discount_percent <= 100 or rec.deduction_amount < 0:
                raise ValidationError(_('Discount must be between 0 and 100 and deductions cannot be negative.'))

    def _check_overlap(self):
        for rec in self:
            rec.contract_id._lock()
            if self.search_count([('id', '!=', rec.id), ('contract_id', '=', rec.contract_id.id), ('state', 'in', ['approved', 'invoiced']),
                                  ('date_start', '<=', rec.date_end), ('date_end', '>=', rec.date_start)]):
                raise ValidationError(_('This contract already has an approved or invoiced billing period that overlaps.'))

    def _check_actual_quantity_reuse(self):
        for rec in self:
            for line in rec.line_ids.filtered(lambda r: r.billing_basis == 'hours'):
                _allocation_lock(line.allocation_ids)
                candidates = self.env['dct.security.billing.line'].search([
                    ('id', '!=', line.id), ('allocation_ids', 'in', line.allocation_ids.ids),
                    ('date_start', '<=', line.date_end), ('date_end', '>=', line.date_start),
                    '|', ('billing_id.state', 'in', ['approved', 'invoiced']), ('billing_id', '=', rec.id)])
                if candidates:
                    raise ValidationError(_('An approved actual-hour quantity in this period is already used by another service line or contract.'))

    def _snapshot_values(self):
        self.ensure_one()
        result = []
        for line in self.contract_id.line_ids:
            first, last = max(self.date_start, line.date_start), min(self.date_end, line.date_end)
            if first > last:
                continue
            account = line.account_id or line.product_id.with_company(self.company_id).property_account_income_id or line.product_id.categ_id.with_company(self.company_id).property_account_income_categ_id
            if not account:
                raise UserError(_('Configure an income account on every effective service line or product.'))
            allocations = self.env['dct.security.allocation']
            start, end = _utc_bounds(line.site_id, first, last)
            if line.billing_basis == 'fixed':
                months = {'monthly': 1, 'quarterly': 3, 'annual': 12}[self.contract_id.billing_cycle]
                if line.proration == 'full_only' and (first.day != 1 or (first.month - 1) % months or
                        (last + timedelta(days=1)).day != 1 or (last + timedelta(days=1)).month % months != 1 % months):
                    raise UserError(_('This service requires whole calendar billing cycles.'))
                quantity = line.quantity * _calendar_fraction(first, last, months)
            elif line.billing_basis == 'guard_shift':
                domain = [('site_id', '=', line.site_id.id), ('company_id', '=', self.company_id.id), ('state', '=', 'published'),
                          ('start', '>=', start), ('start', '<', end)]
                if line.post_id:
                    domain.append(('post_id', '=', line.post_id.id))
                quantity = sum(self.env['dct.security.shift'].search(domain).mapped('required_guards')) * line.quantity
            else:
                domain = [('site_id', '=', line.site_id.id), ('company_id', '=', self.company_id.id), ('state', '=', 'approved'),
                          ('start', '<', end), ('end', '>', start)]
                if line.post_id:
                    domain.append(('assignment_id.shift_id.post_id', '=', line.post_id.id))
                allocations = self.env['dct.security.allocation'].search(domain)
                _allocation_lock(allocations)
                quantity = sum(a.hours * max(0, (min(a.end, end) - max(a.start, start)).total_seconds()) /
                               (a.end - a.start).total_seconds() for a in allocations if a.end > a.start)
            result.append({'billing_id': self.id, 'contract_line_id': line.id, 'name': line.name, 'site_id': line.site_id.id,
                           'date_start': first, 'date_end': last, 'billing_basis': line.billing_basis,
                           'quantity': quantity, 'rate': line.rate, 'product_id': line.product_id.id,
                           'account_id': account.id, 'tax_ids': [Command.set(line.tax_ids.ids)],
                           'allocation_ids': [Command.set(allocations.ids)]})
        if not result:
            raise UserError(_('No effective service lines cover this period.'))
        return result

    def action_prepare(self):
        self._check_role('group_finance')
        for rec in self:
            rec._lock()
            if rec.state != 'draft':
                raise UserError(_('Only draft billing can be recalculated.'))
            if rec.contract_id.state != 'active':
                raise UserError(_('Only active contracts can be billed.'))
            rec.line_ids.with_context(_dct_finance_token=_FINANCE_TOKEN).unlink()
            self.env['dct.security.billing.line'].with_context(_dct_finance_token=_FINANCE_TOKEN).create(rec._snapshot_values())
        return True

    def action_approve(self):
        self._check_role('group_finance')
        for rec in self:
            rec._lock()
            if rec.state in ('approved', 'invoiced'):
                continue
            if rec.state != 'draft':
                raise UserError(_('Only draft billing may be approved.'))
            rec._check_overlap()
            rec.action_prepare()
            rec._check_actual_quantity_reuse()
            if (rec.discount_percent or rec.deduction_amount) and not rec.adjustment_reason:
                raise UserError(_('Record the approval reason for discounts or service deductions.'))
            if rec.deduction_amount and not rec.deduction_product_id:
                raise UserError(_('Select a configured service deduction product.'))
            approval_values = {'state': 'approved', 'approved_by': self.env.uid, 'approved_at': fields.Datetime.now()}
            if rec.deduction_amount:
                product = rec.deduction_product_id.with_company(rec.company_id)
                account = product.property_account_income_id or product.categ_id.property_account_income_categ_id
                if not account:
                    raise UserError(_('Configure the deduction product income account.'))
                approval_values.update({'deduction_account_id': account.id,
                    'deduction_tax_ids': [Command.set(product.taxes_id.filtered(lambda t: t.company_id == rec.company_id).ids)]})
            if rec.amount_total < 0:
                raise UserError(_('A service deduction cannot exceed the approved charge.'))
            super(SecurityBilling, rec).write(approval_values)
        return True

    def action_create_invoice(self):
        self.ensure_one()
        self._check_role('group_finance')
        self._lock()
        self.contract_id._lock()
        if self.invoice_id:
            return self._invoice_action()
        if self.state != 'approved':
            raise UserError(_('Approve billing before creating its draft invoice.'))
        self._check_overlap()
        commands = []
        for line in self.line_ids:
            account = line.account_id or line.product_id.with_company(self.company_id).property_account_income_id or line.product_id.categ_id.with_company(self.company_id).property_account_income_categ_id
            if not account:
                raise UserError(_('Configure an income account on every service line or product.'))
            commands.append(Command.create({'name': '%s | %s | %s - %s | %s × %s %s' % (line.name, line.site_id.display_name, line.date_start, line.date_end,
                format(line.quantity, '.10g'), line.rate, self.currency_id.name),
                'product_id': line.product_id.id, 'account_id': account.id, 'quantity': 1, 'price_unit': line.subtotal,
                'discount': self.discount_percent, 'tax_ids': [Command.set(line.tax_ids.ids)], 'dct_billing_line_id': line.id}))
        if self.deduction_amount:
            product = self.deduction_product_id.with_company(self.company_id)
            account = self.deduction_account_id
            if not account:
                raise UserError(_('Configure the deduction product income account.'))
            commands.append(Command.create({'name': _('Approved deduction: %s', self.adjustment_reason), 'product_id': product.id,
                'account_id': account.id, 'quantity': 1, 'price_unit': -self.deduction_amount,
                'tax_ids': [Command.set(self.deduction_tax_ids.ids)]}))
        invoice = self.env['account.move'].with_company(self.company_id).with_context(_dct_finance_token=_FINANCE_TOKEN).create({'move_type': 'out_invoice', 'partner_id': self.partner_id.id,
            'company_id': self.company_id.id, 'currency_id': self.currency_id.id, 'invoice_date': fields.Date.context_today(self),
            'invoice_payment_term_id': self.contract_id.payment_term_id.id, 'invoice_origin': self.name,
            'dct_billing_id': self.id, 'invoice_line_ids': commands})
        if self.currency_id.compare_amounts(invoice.amount_untaxed, self.amount_total):
            raise UserError(_('Native product price precision cannot represent this approved service amount. Increase Product Price precision before creating the invoice.'))
        super(SecurityBilling, self).write({'invoice_id': invoice.id, 'state': 'invoiced'})
        return self._invoice_action()

    def _invoice_action(self):
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': self.invoice_id.id, 'view_mode': 'form'}

    def action_cancel(self):
        self._check_role('group_finance')
        for rec in self:
            rec._lock()
            rec.contract_id._lock()
            if rec.state == 'cancelled':
                continue
            if not rec.cancellation_reason:
                raise UserError(_('Record the cancellation or rebilling reason.'))
            invoice = rec.invoice_id
            if invoice and invoice.state != 'cancel':
                refunds = self.env['account.move'].search([('reversed_entry_id', '=', invoice.id), ('state', '=', 'posted'), ('move_type', '=', 'out_refund')])
                if invoice.state != 'posted' or not refunds or any(r.currency_id != invoice.currency_id for r in refunds) or invoice.currency_id.compare_amounts(sum(refunds.mapped('amount_total')), invoice.amount_total) != 0:
                    raise UserError(_('Cancel the draft invoice or post an exact full credit note before releasing this period for rebilling. Partial credits do not release the period.'))
            super(SecurityBilling, rec).write({'state': 'cancelled'})
        return True

    @api.model
    def _dashboard_figures(self, company, date_start, date_end, site=False):
        """Accounting and approved cost figures, kept in their source currencies.

        Cash includes only bank-statement matches or settled native payments.
        Credit-note offsets and other reconciliation/write-off entries are not
        cash. Site payment/cost portions and partial-period costs are estimates.
        """
        self._check_role('group_finance')
        company.ensure_one()
        company.check_access('read')
        if company not in self.env.companies:
            raise AccessError(_('Choose a permitted company.'))
        first, last = fields.Date.to_date(date_start), fields.Date.to_date(date_end)
        if not first or not last or first > last:
            raise ValidationError(_('Choose a valid financial reporting period.'))
        if site:
            site = self.env['dct.security.site'].browse(site) if isinstance(site, int) else site
            site.ensure_one()
            site.check_access('read')
            if site.company_id != company:
                raise ValidationError(_('The financial site must belong to the selected company.'))
        moves_model = self.env['account.move']
        moves_model.check_access('read')
        buckets = {}

        def bucket(currency):
            return buckets.setdefault(currency.id, {'currency_id': currency.id, 'currency': currency.name, 'name': currency.name,
                'net': 0.0, 'outstanding': 0.0, 'cash_received': 0.0, 'estimated_cost': 0.0, 'estimated_margin': 0.0,
                'invoice_ids': set(), 'cash_move_ids': set(), 'payroll_ids': set()})

        def site_share(move):
            if not site:
                return 1.0
            sources = move.invoice_line_ids.filtered('dct_billing_line_id')
            total = sum(abs(line.price_subtotal) for line in sources)
            return sum(abs(line.price_subtotal) for line in sources if line.dct_billing_line_id.site_id == site) / total if total else 0.0

        domain = [('company_id', '=', company.id), ('state', '=', 'posted'), ('move_type', 'in', ['out_invoice', 'out_refund']), ('dct_billing_id', '!=', False)]
        if site:
            domain.append(('dct_billing_id.contract_id.site_ids', 'in', site.ids))
        # Include earlier invoices because the selected period can contain their
        # settlement. Native accounting rules filter every source record.
        moves = moves_model.search(domain)
        seen_cash = set()
        for move in moves:
            ratio = site_share(move)
            if not ratio:
                continue
            amounts = bucket(move.currency_id)
            sign = -1 if move.move_type == 'out_refund' else 1
            if first <= (move.invoice_date or move.date) <= last:
                amounts['net'] += sign * move.amount_untaxed * ratio
                amounts['outstanding'] += sign * move.amount_residual * ratio
                amounts['invoice_ids'].add(move.id)
            for line in move.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable'):
                for partial in line.matched_credit_ids | line.matched_debit_ids:
                    if partial.id in seen_cash:
                        continue
                    invoice_is_debit = partial.debit_move_id == line
                    counterpart = partial.credit_move_id if invoice_is_debit else partial.debit_move_id
                    payment_move = counterpart.move_id
                    if payment_move.state != 'posted' or not first <= payment_move.date <= last:
                        continue
                    payment = payment_move.origin_payment_id
                    if not payment_move.statement_line_id and not (payment and payment.is_matched):
                        continue
                    value = partial.debit_amount_currency if invoice_is_debit else partial.credit_amount_currency
                    amounts['cash_received'] += sign * value * ratio
                    amounts['cash_move_ids'].add(payment_move.id)
                    seen_cash.add(partial.id)
        payrolls = self.env['dct.security.payroll'].search([('company_id', '=', company.id), ('state', 'in', _FROZEN_PAY),
            ('date_start', '<=', last), ('date_end', '>=', first)])
        for worksheet in payrolls:
            days = (min(last, worksheet.date_end) - max(first, worksheet.date_start)).days + 1
            fraction = days / ((worksheet.date_end - worksheet.date_start).days + 1)
            ratio = 1.0
            if site:
                bases = worksheet.line_ids.filtered(lambda line: line.kind == 'base')
                base_total = sum(line.amount for line in bases)
                ratio = sum(line.amount for line in bases if line.site_id == site) / base_total if base_total else 0.0
            if ratio:
                amounts = bucket(worksheet.currency_id)
                amounts['estimated_cost'] += worksheet.net_amount * fraction * ratio
                amounts['payroll_ids'].add(worksheet.id)
        for currency_id, amounts in buckets.items():
            currency = self.env['res.currency'].browse(currency_id)
            for field_name in ('net', 'outstanding', 'cash_received', 'estimated_cost'):
                amounts[field_name] = currency.round(amounts[field_name])
            amounts['estimated_margin'] = amounts['net'] - amounts['estimated_cost']
            for field_name in ('invoice_ids', 'cash_move_ids', 'payroll_ids'):
                amounts[field_name] = sorted(amounts[field_name])
        return sorted(buckets.values(), key=lambda row: row['currency'])


class SecurityBillingLine(models.Model):
    _name = 'dct.security.billing.line'
    _description = 'Approved Billing Quantity Snapshot'
    _inherit = 'dct.security.mixin'

    billing_id = fields.Many2one('dct.security.billing', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='billing_id.company_id', store=True)
    currency_id = fields.Many2one(related='billing_id.currency_id', store=True)
    contract_line_id = fields.Many2one('dct.security.contract.line', required=True, ondelete='restrict')
    name = fields.Char(required=True)
    site_id = fields.Many2one('dct.security.site', required=True, check_company=True)
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    billing_basis = fields.Selection([('fixed', 'Fixed period'), ('guard_shift', 'Required guard shifts'), ('hours', 'Approved actual hours')], required=True)
    quantity = fields.Float(required=True, digits=False)
    rate = fields.Monetary(required=True, aggregator=False)
    subtotal = fields.Monetary(compute='_compute_subtotal', store=True, aggregator=False)
    product_id = fields.Many2one('product.product', required=True, check_company=True)
    account_id = fields.Many2one('account.account', check_company=True)
    tax_ids = fields.Many2many('account.tax', check_company=True)
    allocation_ids = fields.Many2many('dct.security.allocation')

    @api.depends('quantity', 'rate')
    def _compute_subtotal(self):
        for rec in self:
            rec.subtotal = rec.quantity * rec.rate

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('_dct_finance_token') is not _FINANCE_TOKEN:
            raise AccessError(_('Billing snapshots are generated by the billing workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Billing snapshots cannot be edited.'))

    def unlink(self):
        if self.env.context.get('_dct_finance_token') is not _FINANCE_TOKEN or any(r.billing_id.state != 'draft' for r in self):
            raise AccessError(_('Confirmed billing snapshots cannot be removed.'))
        return super().unlink()


class SecurityCompensation(models.Model):
    _name = 'dct.security.compensation'
    _description = 'Effective Guard Compensation'
    _inherit = ['dct.security.mixin', 'mail.thread']
    _rec_name = 'employee_id'
    _order = 'date_start desc'

    employee_id = fields.Many2one('hr.employee', required=True, check_company=True, ondelete='restrict', index=True)
    currency_id = fields.Many2one('res.currency', required=True, default=lambda self: self.env.company.currency_id)
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    basis = fields.Selection([('monthly', 'Monthly'), ('hourly', 'Hourly')], default='monthly', required=True)
    rate = fields.Monetary(required=True, aggregator=False)
    monthly_hours = fields.Float(default=208, required=True, help='Configured divisor used to display estimated regular hourly cost.')
    estimated_hourly_cost = fields.Monetary(compute='_compute_hourly_cost', store=True, aggregator=False)
    overtime_rate = fields.Monetary(required=True, aggregator=False, help='Explicit hourly rate for approved overtime. Enter zero only when no overtime is payable.')
    allowance = fields.Monetary(aggregator=False, help='Monthly allowance; calendar day prorated for any worksheet period.')
    journal_id = fields.Many2one('account.journal', check_company=True, domain=[('type', '=', 'general')])
    expense_account_id = fields.Many2one('account.account', check_company=True)
    payable_account_id = fields.Many2one('account.account', check_company=True)
    notes = fields.Text()

    @api.depends('basis', 'rate', 'monthly_hours')
    def _compute_hourly_cost(self):
        for rec in self:
            rec.estimated_hourly_cost = rec.rate / rec.monthly_hours if rec.basis == 'monthly' and rec.monthly_hours else rec.rate

    @api.model_create_multi
    def create(self, vals_list):
        self._check_role('group_finance')
        _employee_lock(self.env['hr.employee'].browse([v['employee_id'] for v in vals_list if v.get('employee_id')]))
        return super().create(vals_list)

    def write(self, vals):
        self._check_role('group_finance')
        _employee_lock(self.employee_id)
        frozen = self.env['dct.security.payroll'].search([('compensation_id', 'in', self.ids), ('state', 'in', _FROZEN_PAY)])
        accounting_setup = {'journal_id', 'expense_account_id', 'payable_account_id'}
        if frozen and (set(vals) - accounting_setup or any(frozen.mapped('move_id'))):
            raise UserError(_('Compensation used by approved worksheets is immutable. Create a future effective record.'))
        return super().write(vals)

    def unlink(self):
        if self.env['dct.security.payroll'].search_count([('compensation_id', 'in', self.ids)]):
            raise UserError(_('Compensation referenced by a worksheet must be retained.'))
        return super().unlink()

    @api.constrains('employee_id', 'company_id', 'date_start', 'date_end', 'rate', 'monthly_hours', 'overtime_rate', 'allowance', 'currency_id')
    def _check_compensation(self):
        for rec in self:
            _employee_lock(rec.employee_id)
            if rec.employee_id.company_id != rec.company_id or not rec.employee_id.is_security_guard:
                raise ValidationError(_('Compensation requires a security guard in the same company.'))
            if rec.date_end < rec.date_start or min(rec.rate, rec.overtime_rate, rec.allowance) < 0 or rec.monthly_hours <= 0:
                raise ValidationError(_('Check compensation dates, nonnegative rates, and the positive hour divisor.'))
            if self.search_count([('id', '!=', rec.id), ('employee_id', '=', rec.employee_id.id), ('company_id', '=', rec.company_id.id),
                                  ('date_start', '<=', rec.date_end), ('date_end', '>=', rec.date_start)]):
                raise ValidationError(_('Effective compensation periods cannot overlap for one guard.'))


class SecurityPayroll(models.Model):
    _name = 'dct.security.payroll'
    _description = 'Guard Payroll Worksheet (Operational Estimate)'
    _inherit = ['dct.security.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    employee_id = fields.Many2one('hr.employee', required=True, check_company=True, ondelete='restrict', index=True)
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    compensation_id = fields.Many2one('dct.security.compensation', readonly=True, copy=False, ondelete='restrict')
    currency_id = fields.Many2one('res.currency', required=True, default=lambda self: self.env.company.currency_id)
    state = fields.Selection([('draft', 'Draft'), ('reviewed', 'Reviewed'), ('approved', 'Approved'), ('exported', 'Exported'), ('accounted', 'Accounted')], required=True, default='draft', tracking=True, copy=False)
    allocation_ids = fields.Many2many('dct.security.allocation', readonly=True, copy=False)
    leave_ids = fields.Many2many('hr.leave', readonly=True, copy=False, help='Approved time off overlapping this period, for review only. No automatic deduction.')
    approved_hours = fields.Float(readonly=True, copy=False)
    overtime_hours = fields.Float(string='Approved overtime hours', readonly=True, copy=False, help='Approved assignment overtime allocated proportionally to attendance in this period. Regular hourly pay excludes these hours.')
    allowance_adjustment = fields.Monetary(aggregator=False, help='Explicit additional allowance approved with this worksheet.')
    deduction_amount = fields.Monetary(aggregator=False, help='Explicit approved deduction. Incidents or absence never create this automatically.')
    adjustment_amount = fields.Monetary(aggregator=False, help='Signed correction from an earlier period; record the source worksheet and reason.')
    adjustment_reason = fields.Text()
    adjustment_of_id = fields.Many2one('dct.security.payroll', check_company=True, ondelete='restrict')
    line_ids = fields.One2many('dct.security.payroll.line', 'payroll_id', copy=False)
    gross_amount = fields.Monetary(compute='_compute_amounts', store=True, aggregator=False)
    allowance_amount = fields.Monetary(compute='_compute_amounts', store=True, aggregator=False)
    net_amount = fields.Monetary(compute='_compute_amounts', store=True, aggregator=False)
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    move_id = fields.Many2one('account.move', check_company=True, readonly=True, copy=False, ondelete='restrict')
    export_file = fields.Binary(readonly=True, attachment=False, copy=False)
    export_filename = fields.Char(readonly=True, copy=False)
    notes = fields.Text()

    @api.depends('employee_id.name', 'date_start', 'date_end')
    def _compute_name(self):
        for rec in self:
            rec.name = '%s / %s - %s' % (rec.employee_id.name or '', rec.date_start or '', rec.date_end or '')

    @api.depends('line_ids.amount', 'line_ids.kind')
    def _compute_amounts(self):
        for rec in self:
            rec.gross_amount = sum(rec.line_ids.filtered(lambda r: r.kind in ('base', 'overtime')).mapped('amount'))
            rec.allowance_amount = sum(rec.line_ids.filtered(lambda r: r.kind == 'allowance').mapped('amount'))
            rec.net_amount = sum(rec.line_ids.mapped('amount'))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_role('group_finance')
        protected = {'compensation_id', 'approved_hours', 'overtime_hours', 'allocation_ids', 'leave_ids', 'line_ids', 'approved_by', 'approved_at', 'move_id', 'export_file', 'export_filename'}
        if any(v.get('state', 'draft') != 'draft' or protected.intersection(v) for v in vals_list):
            raise AccessError(_('Create a draft worksheet and use its workflow actions.'))
        _employee_lock(self.env['hr.employee'].browse([v['employee_id'] for v in vals_list if v.get('employee_id')]))
        return super().create(vals_list)

    def write(self, vals):
        self._check_role('group_finance')
        protected = {'state', 'compensation_id', 'approved_hours', 'overtime_hours', 'allocation_ids', 'leave_ids', 'line_ids', 'approved_by', 'approved_at', 'move_id', 'export_file', 'export_filename'}
        if protected.intersection(vals):
            raise AccessError(_('Worksheet snapshots and workflow fields are controlled by actions.'))
        if set(vals) - {'message_follower_ids', 'activity_ids', 'message_ids'} and any(r.state != 'draft' for r in self):
            raise UserError(_('Reviewed or approved worksheets are locked. Return a review to Draft or use a later adjustment.'))
        _employee_lock(self.employee_id)
        return super().write(vals)

    def unlink(self):
        if any(r.state != 'draft' for r in self):
            raise UserError(_('Reviewed payroll history must be retained.'))
        self.line_ids.with_context(_dct_finance_token=_FINANCE_TOKEN).unlink()
        return super().unlink()

    @api.constrains('employee_id', 'company_id', 'date_start', 'date_end', 'deduction_amount', 'overtime_hours', 'allowance_adjustment', 'adjustment_of_id')
    def _check_period(self):
        for rec in self:
            _employee_lock(rec.employee_id)
            if rec.date_end < rec.date_start or not rec.employee_id.is_security_guard or rec.employee_id.company_id != rec.company_id:
                raise ValidationError(_('Use a valid pay period and a security guard from the worksheet company.'))
            if min(rec.overtime_hours, rec.deduction_amount, rec.allowance_adjustment) < 0:
                raise ValidationError(_('Overtime, allowances, and deductions must be nonnegative.'))
            if rec.adjustment_of_id and (rec.adjustment_of_id.employee_id != rec.employee_id or rec.adjustment_of_id.company_id != rec.company_id or rec.adjustment_of_id.currency_id != rec.currency_id or rec.adjustment_of_id.state not in _FROZEN_PAY or rec.adjustment_of_id.date_end >= rec.date_start):
                raise ValidationError(_('An adjustment must reference an approved earlier worksheet for the same guard, company, and currency.'))
            if self.search_count([('id', '!=', rec.id), ('employee_id', '=', rec.employee_id.id), ('company_id', '=', rec.company_id.id),
                                  ('date_start', '<=', rec.date_end), ('date_end', '>=', rec.date_start)]):
                raise ValidationError(_('Payroll worksheet periods cannot overlap for the same guard and company.'))

    def action_calculate(self):
        self._check_role('group_finance')
        for rec in self:
            rec._lock()
            _employee_lock(rec.employee_id)
            if rec.state != 'draft':
                raise UserError(_('Only draft worksheets can be calculated.'))
            compensation = self.env['dct.security.compensation'].search([('employee_id', '=', rec.employee_id.id), ('company_id', '=', rec.company_id.id),
                ('date_start', '<=', rec.date_start), ('date_end', '>=', rec.date_end)], limit=1)
            if not compensation:
                raise UserError(_('Configure compensation covering the entire period. Split the worksheet at effective rate changes.'))
            compensation._lock()
            if compensation.currency_id != rec.currency_id:
                raise UserError(_('Worksheet currency must match the effective compensation currency.'))
            # Payroll uses the employee resource timezone. Site billing uses the site timezone.
            tz = pytz.timezone(rec.employee_id.tz or 'UTC')
            start = tz.localize(datetime.combine(rec.date_start, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
            end = tz.localize(datetime.combine(rec.date_end + timedelta(days=1), time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
            allocations = self.env['dct.security.allocation'].search([('employee_id', '=', rec.employee_id.id), ('company_id', '=', rec.company_id.id),
                ('state', '=', 'approved'), ('start', '<', end), ('end', '>', start)])
            _allocation_lock(allocations)
            site_hours = {}
            overtime_hours = 0.0
            for allocation in allocations:
                hours = allocation.hours * max(0, (min(allocation.end, end) - max(allocation.start, start)).total_seconds()) / (allocation.end - allocation.start).total_seconds()
                site_hours[allocation.site_id.id] = site_hours.get(allocation.site_id.id, 0) + hours
                assignment = allocation.assignment_id
                if assignment.approved_hours:
                    overtime_hours += assignment.approved_overtime_hours * hours / assignment.approved_hours
            hours = sum(site_hours.values())
            if overtime_hours > hours + 0.000001:
                raise UserError(_('Approved overtime cannot exceed approved worked hours.'))
            if (rec.deduction_amount or rec.allowance_adjustment or rec.adjustment_amount) and not rec.adjustment_reason:
                raise UserError(_('Record a reason for explicit allowances, deductions, or adjustments.'))
            if rec.adjustment_amount and not rec.adjustment_of_id:
                raise UserError(_('Link the earlier approved worksheet for this correction.'))
            fraction = _calendar_fraction(rec.date_start, rec.date_end)
            base = compensation.rate * fraction if compensation.basis == 'monthly' else compensation.rate * (hours - overtime_hours)
            lines = []
            # Monthly salary is estimated and allocated proportionally to approved site hours.
            if hours:
                remaining = rec.currency_id.round(base)
                for index, (site_id, site_hour) in enumerate(site_hours.items()):
                    amount = remaining if index == len(site_hours) - 1 else rec.currency_id.round(base * site_hour / hours)
                    remaining -= amount
                    lines.append({'name': _('Base compensation'), 'kind': 'base', 'site_id': site_id, 'quantity': site_hour, 'rate': amount / site_hour})
            else:
                lines.append({'name': _('Base compensation (unallocated estimate)'), 'kind': 'base', 'quantity': fraction if compensation.basis == 'monthly' else 0, 'rate': compensation.rate})
            lines.extend([{'name': _('Approved overtime'), 'kind': 'overtime', 'quantity': overtime_hours, 'rate': compensation.overtime_rate},
                          {'name': _('Allowance'), 'kind': 'allowance', 'quantity': 1, 'rate': compensation.allowance * fraction + rec.allowance_adjustment},
                          {'name': _('Approved deduction'), 'kind': 'deduction', 'quantity': 1, 'rate': -rec.deduction_amount},
                          {'name': _('Prior-period adjustment'), 'kind': 'adjustment', 'quantity': 1, 'rate': rec.adjustment_amount}])
            rec.line_ids.with_context(_dct_finance_token=_FINANCE_TOKEN).unlink()
            self.env['dct.security.payroll.line'].with_context(_dct_finance_token=_FINANCE_TOKEN).create([dict(v, payroll_id=rec.id) for v in lines])
            # Keep only source IDs, never leave descriptions or medical documents.
            # Employee read access and finance role were checked above; no HR role is granted.
            self.env.cr.execute('SELECT id FROM hr_leave WHERE employee_id = %s AND state = %s AND date_from < %s AND date_to > %s',
                                [rec.employee_id.id, 'validate', end, start])
            leave_ids = [row[0] for row in self.env.cr.fetchall()]
            super(SecurityPayroll, rec).write({'compensation_id': compensation.id, 'allocation_ids': [Command.set(allocations.ids)],
                'leave_ids': [Command.set(leave_ids)], 'approved_hours': hours, 'overtime_hours': overtime_hours})
            if rec.net_amount < 0:
                raise UserError(_('Deductions exceed the payable worksheet amount.'))
        return True

    def action_review(self):
        self._check_role('group_finance')
        for rec in self:
            rec._lock()
            if rec.state == 'reviewed':
                continue
            rec.action_calculate()
            super(SecurityPayroll, rec).write({'state': 'reviewed'})
        return True

    def action_draft(self):
        self._check_role('group_finance')
        self._lock()
        if any(r.state != 'reviewed' for r in self):
            raise UserError(_('Only an unapproved review may return to Draft.'))
        return super().write({'state': 'draft'})

    def action_approve(self):
        self._check_role('group_finance')
        for rec in self:
            rec._lock()
            _employee_lock(rec.employee_id)
            if rec.state in _FROZEN_PAY:
                continue
            if rec.state != 'reviewed':
                raise UserError(_('Review the worksheet before approval.'))
            # Recalculate under the same lock, preserving explicit approval inputs.
            super(SecurityPayroll, rec).write({'state': 'draft'})
            rec.action_calculate()
            super(SecurityPayroll, rec).write({'state': 'approved', 'approved_by': self.env.uid, 'approved_at': fields.Datetime.now()})
        return True

    def action_export(self):
        self.ensure_one()
        self._check_role('group_finance')
        self._lock()
        if self.state not in _FROZEN_PAY:
            raise UserError(_('Approve the worksheet before export.'))
        if not self.export_file:
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['Guard', 'Period start', 'Period end', 'Currency', 'Gross', 'Allowance', 'Deduction', 'Adjustment', 'Net', 'Status'])
            guard_name = self.employee_id.name or ''
            if guard_name.startswith(('=', '+', '-', '@')):
                guard_name = "'" + guard_name
            writer.writerow([guard_name, self.date_start, self.date_end, self.currency_id.name, self.gross_amount, self.allowance_amount,
                self.deduction_amount, self.adjustment_amount, self.net_amount, 'Approved worksheet; not proof of payment'])
            super(SecurityPayroll, self).write({'export_file': base64.b64encode(output.getvalue().encode('utf-8-sig')),
                'export_filename': 'security-payroll-%s.csv' % self.id, 'state': 'accounted' if self.move_id else 'exported'})
        return {'type': 'ir.actions.act_url', 'url': '/web/content/dct.security.payroll/%s/export_file/%s?download=true' % (self.id, self.export_filename), 'target': 'self'}

    def action_create_entry(self):
        self.ensure_one()
        self._check_role('group_finance')
        self._lock()
        if self.move_id:
            return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': self.move_id.id, 'view_mode': 'form'}
        if self.state not in _FROZEN_PAY:
            raise UserError(_('Approve the worksheet before creating a journal entry.'))
        settings = self.compensation_id
        _employee_lock(self.employee_id)
        settings._lock()
        if not settings.journal_id or not settings.expense_account_id or not settings.payable_account_id:
            raise UserError(_('Configure the compensation journal, expense account, and payable account.'))
        if settings.journal_id.type != 'general' or self.net_amount <= 0:
            raise UserError(_('Use a miscellaneous journal and a positive net payable amount.'))
        amount = self.currency_id._convert(self.net_amount, self.company_id.currency_id, self.company_id, self.date_end)
        common = {'name': self.name, 'currency_id': self.currency_id.id, 'partner_id': self.employee_id.work_contact_id.id}
        move = self.env['account.move'].with_company(self.company_id).with_context(_dct_finance_token=_FINANCE_TOKEN).create({'move_type': 'entry', 'date': self.date_end,
            'company_id': self.company_id.id, 'journal_id': settings.journal_id.id, 'ref': self.name, 'dct_payroll_id': self.id,
            'line_ids': [Command.create(dict(common, account_id=settings.expense_account_id.id, debit=amount, credit=0, amount_currency=self.net_amount)),
                         Command.create(dict(common, account_id=settings.payable_account_id.id, debit=0, credit=amount, amount_currency=-self.net_amount))]})
        super(SecurityPayroll, self).write({'move_id': move.id, 'state': 'accounted'})
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': move.id, 'view_mode': 'form'}


class SecurityPayrollLine(models.Model):
    _name = 'dct.security.payroll.line'
    _description = 'Frozen Payroll Calculation Line'
    _inherit = 'dct.security.mixin'

    payroll_id = fields.Many2one('dct.security.payroll', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='payroll_id.company_id', store=True)
    currency_id = fields.Many2one(related='payroll_id.currency_id', store=True)
    name = fields.Char(required=True)
    kind = fields.Selection([('base', 'Base'), ('overtime', 'Overtime'), ('allowance', 'Allowance'), ('deduction', 'Deduction'), ('adjustment', 'Adjustment')], required=True)
    site_id = fields.Many2one('dct.security.site', check_company=True)
    quantity = fields.Float(required=True)
    rate = fields.Float(required=True, digits=False, aggregator=False, help='Snapshot rate preserves full precision so site allocation does not introduce extra rounding.')
    amount = fields.Monetary(compute='_compute_amount', store=True, aggregator=False)

    @api.depends('quantity', 'rate')
    def _compute_amount(self):
        for rec in self:
            rec.amount = rec.quantity * rec.rate

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('_dct_finance_token') is not _FINANCE_TOKEN:
            raise AccessError(_('Payroll lines are generated by worksheet actions.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Payroll snapshots cannot be edited.'))

    def unlink(self):
        if self.env.context.get('_dct_finance_token') is not _FINANCE_TOKEN or any(r.payroll_id.state != 'draft' for r in self):
            raise AccessError(_('Reviewed payroll snapshots cannot be removed.'))
        return super().unlink()


class AccountMove(models.Model):
    _inherit = 'account.move'

    dct_billing_id = fields.Many2one('dct.security.billing', string='Security billing', copy=False, readonly=True, ondelete='restrict', check_company=True)
    dct_payroll_id = fields.Many2one('dct.security.payroll', string='Security payroll worksheet', copy=False, readonly=True, ondelete='restrict', check_company=True)

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('_dct_finance_token') is not _FINANCE_TOKEN and any(v.get('dct_billing_id') or v.get('dct_payroll_id') for v in vals_list):
            raise AccessError(_('Security accounting links are set only by their source workflow.'))
        for values in vals_list:
            original = self.browse(values.get('reversed_entry_id'))
            if original and original.dct_billing_id.state == 'cancelled':
                raise UserError(_('This security billing period has been released for rebilling. Its cancellation and credit documents are frozen.'))
            if original.dct_billing_id and values.get('move_type') == 'out_refund':
                # Native manual credit notes retain the same trace as credits
                # created by the reversal wizard. The source is derived here,
                # never trusted from an externally supplied billing ID.
                values['dct_billing_id'] = original.dct_billing_id.id
        return super().create(vals_list)

    def _closed_security_billing(self):
        return self.filtered(lambda move: (move.dct_billing_id or move.reversed_entry_id.dct_billing_id).state == 'cancelled')

    def write(self, vals):
        if {'dct_billing_id', 'dct_payroll_id'}.intersection(vals) and self.env.context.get('_dct_finance_token') is not _FINANCE_TOKEN:
            raise AccessError(_('Security accounting source links are immutable.'))
        if 'reversed_entry_id' in vals and any((move.dct_billing_id or move.reversed_entry_id.dct_billing_id)
                and move.reversed_entry_id.id != (vals['reversed_entry_id'] or False) for move in self):
            raise AccessError(_('Security accounting source links are immutable.'))
        if 'state' in vals and self._closed_security_billing().filtered(lambda move: move.state != vals['state']):
            raise UserError(_('Documents used to release a security billing period cannot be reopened or cancelled. Use a new approved adjustment.'))
        if {'partner_id', 'company_id', 'currency_id', 'move_type'}.intersection(vals) and any(m.dct_billing_id or m.dct_payroll_id for m in self):
            for move in self:
                if any(key in vals and vals[key] != (move[key].id if key != 'move_type' else move[key]) for key in ('partner_id', 'company_id', 'currency_id', 'move_type')):
                    raise UserError(_('Customer, company, currency, and type are frozen for security accounting documents.'))
        return super().write(vals)

    def _reverse_moves(self, default_values_list=None, cancel=False):
        if self._closed_security_billing():
            raise UserError(_('Documents for released security billing periods are frozen. Use a new approved billing adjustment.'))
        defaults = default_values_list or [{} for _ in self]
        for move, values in zip(self, defaults):
            if move.dct_billing_id:
                values['dct_billing_id'] = move.dct_billing_id.id
        return super(AccountMove, self.with_context(_dct_finance_token=_FINANCE_TOKEN))._reverse_moves(default_values_list=defaults, cancel=cancel)

    def unlink(self):
        if any(move.dct_billing_id or move.dct_payroll_id for move in self) or self._closed_security_billing():
            raise UserError(_('Retain linked security accounting documents. Cancel or reverse them through accounting.'))
        return super().unlink()


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    dct_billing_line_id = fields.Many2one('dct.security.billing.line', string='Security service snapshot', readonly=True, copy=True, ondelete='restrict', check_company=True)

    def _locked_security_source(self):
        return self.filtered(lambda line: (line.move_id.dct_billing_id and line.move_id.move_type == 'out_invoice' and
            line.move_id.dct_billing_id.invoice_id == line.move_id) or (line.move_id.dct_payroll_id and line.move_id.dct_payroll_id.move_id == line.move_id)
            or bool(line.move_id._closed_security_billing()))

    @api.model_create_multi
    def create(self, vals_list):
        trusted = self.env.context.get('_dct_finance_token') is _FINANCE_TOKEN
        if not trusted:
            for vals in vals_list:
                if vals.get('dct_billing_line_id'):
                    raise AccessError(_('Security billing links are set by the source workflow.'))
                move = self.env['account.move'].browse(vals.get('move_id') or self.env.context.get('default_move_id'))
                if move and vals.get('display_type', 'product') == 'product' and ((move.dct_billing_id and move.move_type == 'out_invoice') or move.dct_payroll_id):
                    raise UserError(_('Add charges through a new approved security billing or payroll adjustment.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'dct_billing_line_id' in vals and self.env.context.get('_dct_finance_token') is not _FINANCE_TOKEN:
            raise AccessError(_('Security billing source links are immutable.'))
        if {'move_id', 'display_type', 'product_uom_id', 'quantity', 'price_unit', 'discount', 'product_id', 'tax_ids', 'account_id', 'currency_id', 'amount_currency', 'debit', 'credit', 'balance'}.intersection(vals) and self.env.context.get('_dct_finance_token') is not _FINANCE_TOKEN:
            locked = self._locked_security_source().filtered(lambda r: r.display_type == 'product')
            if locked:
                raise UserError(_('Security accounting amounts are approved snapshots. Cancel or reverse the document and use a controlled source adjustment.'))
        return super().write(vals)

    def unlink(self):
        if self._locked_security_source().filtered(lambda r: r.display_type == 'product'):
            raise UserError(_('Retain approved security accounting lines. Cancel or reverse the document.'))
        return super().unlink()
