import logging

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class SecurityContract(models.Model):
    _name = 'dct.security.contract'
    _description = 'Security Service Contract'
    _inherit = ['dct.security.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    name = fields.Char(required=True, tracking=True)
    partner_id = fields.Many2one('res.partner', required=True, check_company=True, tracking=True)
    site_ids = fields.Many2many('dct.security.site', string='Sites', check_company=True)
    date_start = fields.Date(required=True, tracking=True)
    date_end = fields.Date(required=True, tracking=True)
    state = fields.Selection([('draft', 'Draft'), ('active', 'Active'), ('suspended', 'Suspended'),
                              ('expired', 'Expired'), ('cancelled', 'Cancelled')], default='draft', required=True, tracking=True, copy=False)
    currency_id = fields.Many2one('res.currency', required=True, default=lambda self: self.env.company.currency_id)
    billing_cycle = fields.Selection([('monthly', 'Monthly'), ('quarterly', 'Quarterly'), ('annual', 'Annual')], default='monthly', required=True)
    payment_term_id = fields.Many2one('account.payment.term', check_company=True)
    line_ids = fields.One2many('dct.security.contract.line', 'contract_id', string='Effective service lines')
    notes = fields.Html()
    billing_ids = fields.One2many('dct.security.billing', 'contract_id', groups='dct_security_management.group_finance')
    auto_billing = fields.Boolean(string='Enable approved-policy draft billing', groups='dct_security_management.group_finance',
                                 help='The scheduled job creates draft monthly billing reviews. Approval and invoice creation remain manual.')

    @api.model_create_multi
    def create(self, vals_list):
        self._check_role('group_manager', 'group_finance')
        if any(vals.get('state', 'draft') != 'draft' for vals in vals_list):
            raise AccessError(_('Create contracts in Draft and use the workflow buttons.'))
        return super().create(vals_list)

    def write(self, vals):
        self._check_role('group_manager', 'group_finance')
        if 'state' in vals:
            raise AccessError(_('Use the contract workflow buttons.'))
        if set(vals) & {'partner_id', 'company_id', 'site_ids', 'date_start', 'date_end', 'currency_id', 'billing_cycle', 'payment_term_id'} and any(r.state != 'draft' for r in self):
            raise UserError(_('Contract terms are locked after activation. Create a new contract or effective-dated service line.'))
        if 'auto_billing' in vals:
            self._check_role('group_finance')
        return super().write(vals)

    def unlink(self):
        self._check_role('group_manager', 'group_finance')
        if any(r.state != 'draft' for r in self):
            raise UserError(_('Confirmed contracts must be retained.'))
        return super().unlink()

    @api.constrains('date_start', 'date_end', 'site_ids', 'partner_id', 'company_id')
    def _check_contract(self):
        for rec in self:
            if rec.date_end < rec.date_start:
                raise ValidationError(_('The contract end date must follow its start date.'))
            if any(s.company_id != rec.company_id or s.partner_id.commercial_partner_id != rec.partner_id.commercial_partner_id for s in rec.site_ids):
                raise ValidationError(_('Every site must belong to the contract customer and company.'))

    def _transition(self, target, allowed):
        self._check_role('group_manager')
        self._lock()
        for rec in self:
            if rec.state == target:
                continue
            if rec.state not in allowed:
                raise UserError(_('Invalid contract transition.'))
            if target == 'active' and (not rec.site_ids or not rec.line_ids):
                raise UserError(_('Add sites and service lines before activation.'))
            super(SecurityContract, rec).write({'state': target})
        return True

    def action_activate(self):
        return self._transition('active', ('draft', 'suspended'))

    def action_suspend(self):
        return self._transition('suspended', ('active',))

    def action_expire(self):
        if any(r.date_end >= fields.Date.context_today(r) for r in self):
            raise UserError(_('A contract can expire only after its end date.'))
        return self._transition('expired', ('active', 'suspended'))

    def action_cancel(self):
        return self._transition('cancelled', ('draft', 'active', 'suspended'))

    def action_new_billing(self):
        self.ensure_one()
        self._check_role('group_finance')
        return {'type': 'ir.actions.act_window', 'res_model': 'dct.security.billing', 'view_mode': 'form',
                'target': 'current', 'context': {'default_contract_id': self.id}}

    @api.model
    def _cron_draft_billing(self):
        """Draft review only; contract lock makes concurrent retries idempotent."""
        today = fields.Date.today()
        end = today.replace(day=1) - relativedelta(days=1)
        start = end.replace(day=1)
        for contract in self.search([('company_id', '=', self.env.company.id), ('company_id.dct_automation_enabled', '=', True), ('auto_billing', '=', True), ('state', '=', 'active'), ('date_start', '<=', end), ('date_end', '>=', start)], limit=200):
            try:
                with self.env.cr.savepoint():
                    contract._lock()
                    first, last = max(start, contract.date_start), min(end, contract.date_end)
                    if not self.env['dct.security.billing'].search_count([('contract_id', '=', contract.id), ('state', '!=', 'cancelled'), ('date_start', '<=', last), ('date_end', '>=', first)]):
                        self.env['dct.security.billing'].create({'contract_id': contract.id, 'date_start': first, 'date_end': last})
            except Exception:
                logging.getLogger(__name__).exception('DCT draft billing failed for contract %s', contract.id)


class SecurityContractLine(models.Model):
    _name = 'dct.security.contract.line'
    _description = 'Effective Security Service Line'
    _inherit = 'dct.security.mixin'
    _order = 'date_start, id'

    name = fields.Char(required=True)
    contract_id = fields.Many2one('dct.security.contract', required=True, ondelete='cascade', check_company=True, index=True)
    company_id = fields.Many2one(related='contract_id.company_id', store=True, readonly=True)
    currency_id = fields.Many2one(related='contract_id.currency_id', store=True)
    site_id = fields.Many2one('dct.security.site', required=True, check_company=True, index=True)
    post_id = fields.Many2one('dct.security.post', check_company=True)
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    billing_basis = fields.Selection([('fixed', 'Fixed period'), ('guard_shift', 'Required guard shifts'), ('hours', 'Approved actual hours')], required=True, default='fixed')
    rate = fields.Monetary(required=True, aggregator=False, groups='dct_security_management.group_finance')
    quantity = fields.Float(default=1, required=True, help='Fixed service units or a multiplier per required guard shift. Actual hours ignore this field.')
    required_guards = fields.Integer(default=1, help='Contractual coverage requirement; shift slots record the actual dated requirement.')
    product_id = fields.Many2one('product.product', required=True, check_company=True)
    account_id = fields.Many2one('account.account', string='Income account', check_company=True, groups='dct_security_management.group_finance')
    tax_ids = fields.Many2many('account.tax', string='Configured sales taxes', check_company=True, groups='dct_security_management.group_finance')
    proration = fields.Selection([('calendar', 'Calendar day proration'), ('full_only', 'Whole calendar cycles only')], required=True, default='calendar')

    @api.model_create_multi
    def create(self, vals_list):
        self._check_role('group_finance')
        contracts = self.env['dct.security.contract'].browse([v['contract_id'] for v in vals_list if v.get('contract_id')])
        contracts._lock()
        records = super().create(vals_list)
        for rec in records:
            if rec.contract_id.state != 'draft' and rec.date_start <= fields.Date.today():
                raise UserError(_('New lines on an activated contract must take effect in the future.'))
        return records

    def write(self, vals):
        self._check_role('group_finance')
        self.mapped('contract_id')._lock()
        if any(r.contract_id.state != 'draft' for r in self):
            raise UserError(_('Activated service lines are immutable. Add a non-overlapping future line or create a successor contract.'))
        return super().write(vals)

    def unlink(self):
        self._check_role('group_finance')
        if any(r.contract_id.state != 'draft' for r in self):
            raise UserError(_('Activated service lines must be retained.'))
        return super().unlink()

    @api.constrains('contract_id', 'site_id', 'post_id', 'date_start', 'date_end', 'product_id', 'billing_basis', 'quantity', 'required_guards')
    def _check_line(self):
        for rec in self:
            c = rec.contract_id
            if rec.site_id not in c.site_ids or rec.site_id.company_id != c.company_id or (rec.post_id and rec.post_id.site_id != rec.site_id):
                raise ValidationError(_('The service site/post must belong to the contract.'))
            if not c.date_start <= rec.date_start <= rec.date_end <= c.date_end:
                raise ValidationError(_('Service dates must be within the contract dates.'))
            if rec.quantity <= 0 or rec.required_guards < 1:
                raise ValidationError(_('Service quantity and required coverage must be positive.'))
            c._lock()
            if self.search_count([('id', '!=', rec.id), ('contract_id', '=', c.id), ('site_id', '=', rec.site_id.id),
                                  ('post_id', '=', rec.post_id.id or False), ('product_id', '=', rec.product_id.id),
                                  ('billing_basis', '=', rec.billing_basis), ('date_start', '<=', rec.date_end), ('date_end', '>=', rec.date_start)]):
                raise ValidationError(_('Effective dates overlap for the same service, site, post, and billing basis.'))

    @api.constrains('rate', 'tax_ids', 'account_id')
    def _check_financial_setup(self):
        for rec in self:
            if rec.rate < 0:
                raise ValidationError(_('Rates cannot be negative; use an approved deduction.'))
            if any(t.type_tax_use not in ('sale', 'none') for t in rec.tax_ids):
                raise ValidationError(_('Select sales taxes for contract billing.'))
