from datetime import date

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from .common import SecurityCase
from ..models.finance import _calendar_fraction, _utc_bounds


@tagged('post_install', '-at_install')
class TestSecurityFinance(SecurityCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.finance = new_test_user(cls.env, login='dct_test_finance',
            groups='base.group_user,dct_security_management.group_finance,account.group_account_user', company_id=cls.company.id)
        cls.income = cls.env['account.account'].create({'name': 'Test Security Income', 'code': 'DCT4100', 'account_type': 'income', 'company_ids': [Command.set(cls.company.ids)]})
        cls.expense = cls.env['account.account'].create({'name': 'Test Guard Cost', 'code': 'DCT5100', 'account_type': 'expense', 'company_ids': [Command.set(cls.company.ids)]})
        cls.payable = cls.env['account.account'].create({'name': 'Test Payroll Accrual', 'code': 'DCT2100', 'account_type': 'liability_current', 'company_ids': [Command.set(cls.company.ids)]})
        cls.receivable = cls.env['account.account'].create({'name': 'Test Security Receivable', 'code': 'DCT1100', 'account_type': 'asset_receivable', 'reconcile': True, 'company_ids': [Command.set(cls.company.ids)]})
        cls.customer.with_company(cls.company).property_account_receivable_id = cls.receivable
        cls.sale_journal = cls.env['account.journal'].create({'name': 'Test Security Sales', 'code': 'DCTS', 'type': 'sale', 'company_id': cls.company.id, 'default_account_id': cls.income.id})
        cls.pay_journal = cls.env['account.journal'].create({'name': 'Test Security Payroll', 'code': 'DCTP', 'type': 'general', 'company_id': cls.company.id})
        cls.product = cls.env['product.product'].create({'name': 'Test Guard Service', 'type': 'service', 'property_account_income_id': cls.income.id, 'taxes_id': [Command.clear()]})
        cls.contract = cls.env['dct.security.contract'].create({'name': 'TEST Contract', 'company_id': cls.company.id,
            'partner_id': cls.customer.id, 'site_ids': [Command.set(cls.site.ids)], 'date_start': '2026-01-01', 'date_end': '2026-12-31'})
        cls.contract_line = cls.env['dct.security.contract.line'].create({'name': 'Main gate fixed service', 'contract_id': cls.contract.id,
            'site_id': cls.site.id, 'post_id': cls.post.id, 'date_start': '2026-01-01', 'date_end': '2026-12-31',
            'billing_basis': 'fixed', 'rate': 3100, 'quantity': 1, 'required_guards': 2,
            'product_id': cls.product.id, 'account_id': cls.income.id})
        cls.contract.action_activate()

    def _billing(self, start='2026-01-01', end='2026-01-31', contract=None):
        return self.env['dct.security.billing'].with_user(self.finance).create({'contract_id': (contract or self.contract).id, 'date_start': start, 'date_end': end})

    def _compensation(self, **changes):
        vals = {'employee_id': self.guard.id, 'company_id': self.company.id, 'date_start': '2026-01-01', 'date_end': '2026-12-31',
            'basis': 'monthly', 'rate': 3100, 'monthly_hours': 208, 'overtime_rate': 20, 'allowance': 310,
            'journal_id': self.pay_journal.id, 'expense_account_id': self.expense.id, 'payable_account_id': self.payable.id}
        vals.update(changes)
        return self.env['dct.security.compensation'].create(vals)

    def _payroll(self, **changes):
        vals = {'employee_id': self.guard.id, 'company_id': self.company.id, 'date_start': '2026-01-01', 'date_end': '2026-01-31'}
        vals.update(changes)
        return self.env['dct.security.payroll'].with_user(self.finance).create(vals)

    def _approved_work(self, start='2026-01-15 05:00:00', end='2026-01-15 13:00:00'):
        shift = self.env['dct.security.shift'].create({'name': 'Finance test shift', 'site_id': self.site.id, 'post_id': self.post.id,
            'company_id': self.company.id, 'start': start, 'end': end, 'required_guards': 2})
        assignment = self.env['dct.security.assignment'].create({'shift_id': shift.id, 'employee_id': self.guard.id, 'company_id': self.company.id})
        shift.action_publish()
        self.env['hr.attendance'].create({'employee_id': self.guard.id, 'check_in': start, 'check_out': end})
        assignment.action_reconcile_attendance()
        assignment.allocation_ids.action_approve()
        return assignment

    def test_contract_workflow_and_frozen_rates(self):
        with self.assertRaises(AccessError):
            self.contract.write({'state': 'draft'})
        with self.assertRaises(UserError):
            self.contract_line.write({'rate': 1})
        with self.assertRaises(UserError):
            self.contract.write({'currency_id': self.env.ref('base.EUR').id})
        self.contract.action_suspend()
        with self.assertRaises(UserError):
            self._billing().action_prepare()
        self.contract.action_activate()

    def test_billing_partial_idempotency_and_snapshot(self):
        first = self._billing(end='2026-01-15')
        first.action_approve()
        self.assertAlmostEqual(first.amount_total, 1500)
        first.action_approve()
        first.action_create_invoice()
        invoice = first.invoice_id
        self.assertEqual(invoice.state, 'draft')
        self.assertAlmostEqual(invoice.amount_untaxed, first.amount_total)
        self.assertEqual(invoice.invoice_line_ids.dct_billing_line_id, first.line_ids)
        first.action_create_invoice()
        self.assertEqual(first.invoice_id, invoice)
        with self.assertRaises(UserError):
            invoice.invoice_line_ids.write({'price_unit': 5})
        second = self._billing(start='2026-01-16')
        second.action_approve()
        self.assertAlmostEqual(first.amount_total + second.amount_total, 3100)
        duplicate = self._billing(start='2026-01-15', end='2026-01-16')
        with self.assertRaises(ValidationError):
            duplicate.action_approve()
        with self.assertRaises(AccessError):
            first.write({'invoice_id': False})
        with self.assertRaises(AccessError):
            first.line_ids.write({'quantity': 99})

    def test_cancellation_and_rebilling(self):
        original = self._billing()
        original.action_approve()
        original.action_create_invoice()
        original.cancellation_reason = 'Replace the cancelled draft invoice'
        with self.assertRaises(UserError):
            original.action_cancel()
        original.invoice_id.button_cancel()
        original.action_cancel()
        replacement = self._billing()
        replacement.action_approve()
        replacement.action_create_invoice()
        self.assertNotEqual(original.invoice_id, replacement.invoice_id)
        with self.assertRaises(UserError):
            original.invoice_id.button_draft()
        with self.assertRaises(UserError):
            original.invoice_id.write({'state': 'draft'})

    def test_full_refund_releases_period_and_preserves_trace(self):
        billing = self._billing()
        billing.action_approve()
        billing.action_create_invoice()
        invoice = billing.invoice_id
        invoice.action_post()
        self.assertEqual(invoice.state, 'posted')
        refund = invoice._reverse_moves([{'date': invoice.date, 'invoice_date': invoice.invoice_date}])
        self.assertEqual(refund.dct_billing_id, billing)
        refund.action_post()
        billing.cancellation_reason = 'Full approved credit note'
        billing.action_cancel()
        self.assertEqual(billing.state, 'cancelled')
        with self.assertRaises(UserError):
            refund.button_draft()

    def test_actual_hours_are_approved_and_partitioned(self):
        assignment = self._approved_work(start='2026-01-31 19:00:00', end='2026-02-01 03:00:00')
        contract = self.env['dct.security.contract'].create({'name': 'Hourly overnight test', 'company_id': self.company.id,
            'partner_id': self.customer.id, 'site_ids': [Command.set(self.site.ids)], 'date_start': '2026-01-01', 'date_end': '2026-12-31'})
        self.env['dct.security.contract.line'].create({'name': 'Approved service hours', 'contract_id': contract.id, 'site_id': self.site.id,
            'date_start': '2026-01-01', 'date_end': '2026-12-31', 'billing_basis': 'hours', 'rate': 10, 'product_id': self.product.id})
        contract.action_activate()
        january = self._billing(contract=contract)
        january.action_approve()
        february = self._billing(start='2026-02-01', end='2026-02-28', contract=contract)
        february.action_approve()
        self.assertAlmostEqual(january.line_ids.quantity, 2)
        self.assertAlmostEqual(february.line_ids.quantity, 6)
        self.assertEqual(january.line_ids.allocation_ids, assignment.allocation_ids)
        self.assertAlmostEqual(january.amount_total + february.amount_total, 80)

    def test_payroll_approved_hours_freeze_export_and_single_entry(self):
        settings = self._compensation(basis='hourly', rate=10, allowance=0)
        assignment = self._approved_work()
        payroll = self._payroll()
        payroll.action_review()
        self.assertAlmostEqual(payroll.approved_hours, 8)
        self.assertAlmostEqual(payroll.net_amount, 80)
        self.assertEqual(payroll.allocation_ids, assignment.allocation_ids)
        payroll.action_approve()
        payroll.action_approve()
        payroll.action_export()
        snapshot = payroll.export_file
        payroll.action_export()
        self.assertEqual(snapshot, payroll.export_file)
        payroll.action_create_entry()
        move = payroll.move_id
        payroll.action_create_entry()
        self.assertEqual(payroll.move_id, move)
        self.assertEqual(move.state, 'draft')
        self.assertAlmostEqual(sum(move.line_ids.mapped('balance')), 0)
        with self.assertRaises(UserError):
            payroll.write({'deduction_amount': 5})
        with self.assertRaises(UserError):
            settings.write({'rate': 99})
        with self.assertRaises(AccessError):
            payroll.write({'state': 'draft'})

    def test_payroll_overlap_missing_configuration_and_finance_access(self):
        settings = self._compensation(journal_id=False)
        payroll = self._payroll()
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._payroll(date_start='2026-01-15', date_end='2026-02-15')
        payroll.action_review()
        payroll.action_approve()
        with self.assertRaises(UserError):
            payroll.action_create_entry()
        with self.assertRaises(AccessError):
            payroll.with_user(self.manager).action_export()
        with self.assertRaises(AccessError):
            self._billing().with_user(self.manager).action_approve()
        # Missing optional setup is repairable without changing approved pay.
        approved_net = payroll.net_amount
        settings.with_user(self.finance).write({'journal_id': self.pay_journal.id})
        payroll.action_create_entry()
        self.assertEqual(payroll.net_amount, approved_net)
        with self.assertRaises(UserError):
            settings.with_user(self.finance).write({'journal_id': False})

    def test_supervisor_hr_cannot_mutate_contracts_or_rates(self):
        supervisor = new_test_user(self.env, login='dct_finance_scope_supervisor',
            groups='base.group_user,dct_security_management.group_supervisor', company_id=self.company.id)
        hr = new_test_user(self.env, login='dct_finance_scope_hr',
            groups='base.group_user,dct_security_management.group_hr', company_id=self.company.id)
        self.site.supervisor_ids = [Command.link(supervisor.id)]
        for user in (supervisor, hr):
            self.assertEqual(self.contract.with_user(user).name, self.contract.name)
            with self.assertRaises(AccessError):
                self.contract.with_user(user).write({'name': 'Unauthorized edit'})
            with self.assertRaises(AccessError):
                self.contract.with_user(user).action_suspend()
            with self.assertRaises(AccessError):
                self.contract_line.with_user(user).write({'quantity': 7})
            with self.assertRaises(AccessError):
                self.contract_line.with_user(user).read(['rate'])
            with self.assertRaises(AccessError):
                self.env['dct.security.contract'].with_user(user).create({'name': 'Unauthorized', 'company_id': self.company.id,
                    'partner_id': self.customer.id, 'site_ids': [Command.set(self.site.ids)], 'date_start': '2026-01-01', 'date_end': '2026-12-31'})
        with self.assertRaises(AccessError):
            self.contract_line.with_user(self.manager).write({'quantity': 2})

    def test_accounting_and_snapshot_forgery_is_denied(self):
        bill = self._billing()
        bill.action_approve()
        bill.action_create_invoice()
        move = bill.invoice_id
        with self.assertRaises(AccessError):
            self.env['account.move'].with_user(self.finance).create({'move_type': 'out_invoice', 'dct_billing_id': bill.id})
        with self.assertRaises(AccessError):
            move.write({'dct_billing_id': False})
        with self.assertRaises(AccessError):
            move.invoice_line_ids.write({'dct_billing_line_id': False})
        with self.assertRaises(UserError):
            move.write({'invoice_line_ids': [Command.update(move.invoice_line_ids.id, {'quantity': 99})]})
        other_invoice = self.env['account.move'].with_user(self.finance).create({'move_type': 'out_invoice',
            'partner_id': self.customer.id, 'company_id': self.company.id})
        original_line_ids = move.line_ids.ids
        with self.assertRaises(UserError):
            move.line_ids.write({'move_id': other_invoice.id})
        with self.assertRaises(UserError):
            move.invoice_line_ids.write({'display_type': 'line_note'})
        with self.assertRaises(UserError):
            move.invoice_line_ids.write({'product_uom_id': False})
        self.assertEqual(move.line_ids.ids, original_line_ids)
        self.assertFalse(other_invoice.line_ids)
        with self.assertRaises(UserError):
            self.env['account.move.line'].with_user(self.finance).create({'move_id': move.id, 'name': 'Unapproved extra charge',
                'account_id': self.income.id, 'product_id': self.product.id, 'quantity': 1, 'price_unit': 100})
        with self.assertRaises(AccessError):
            bill.with_context(_dct_finance_token='forged').write({'state': 'draft'})
        with self.assertRaises(AccessError):
            self.env['dct.security.billing.line'].with_user(self.finance).with_context(_dct_finance_token='forged').create({
                'billing_id': bill.id, 'contract_line_id': self.contract_line.id, 'name': 'Forged approved snapshot',
                'site_id': self.site.id, 'date_start': '2026-01-01', 'date_end': '2026-01-31',
                'billing_basis': 'hours', 'quantity': 500, 'rate': 99, 'product_id': self.product.id})
        self.assertAlmostEqual(move.amount_untaxed, 3100)

    def test_manual_release_credit_source_is_immutable(self):
        bill = self._billing()
        bill.action_approve()
        bill.action_create_invoice()
        invoice = bill.invoice_id
        invoice.action_post()
        # A native accountant may record a manual credit linked to the original
        # invoice without using the security source-link field.
        refund = self.env['account.move'].with_user(self.finance).create({'move_type': 'out_refund',
            'company_id': self.company.id, 'partner_id': self.customer.id, 'currency_id': invoice.currency_id.id,
            'invoice_date': invoice.invoice_date, 'reversed_entry_id': invoice.id,
            'invoice_line_ids': [Command.create({'name': 'Manual full credit', 'product_id': self.product.id,
                'account_id': self.income.id, 'quantity': 1, 'price_unit': invoice.amount_untaxed, 'tax_ids': [Command.clear()]})]})
        refund.action_post()
        self.assertEqual(refund.dct_billing_id, bill)
        bill.cancellation_reason = 'Native manual full credit'
        bill.action_cancel()
        with self.assertRaises(AccessError):
            refund.write({'reversed_entry_id': False})
        with self.assertRaises(UserError):
            refund.button_draft()
        with self.assertRaises(UserError):
            refund.unlink()

    def test_partial_refund_does_not_release_billing_period(self):
        bill = self._billing()
        bill.action_approve()
        bill.action_create_invoice()
        invoice = bill.invoice_id
        invoice.action_post()
        refund = invoice._reverse_moves([{'date': invoice.date, 'invoice_date': invoice.invoice_date}])
        refund.invoice_line_ids.write({'price_unit': refund.invoice_line_ids.price_unit / 2})
        refund.action_post()
        self.assertAlmostEqual(refund.amount_total, invoice.amount_total / 2)
        self.assertEqual(refund.dct_billing_id, bill)
        bill.cancellation_reason = 'A partial credit must retain the reserved period'
        with self.assertRaises(UserError):
            bill.action_cancel()
        self.assertEqual(bill.state, 'invoiced')
        duplicate = self._billing()
        with self.assertRaises(ValidationError):
            duplicate.action_approve()

    def test_actual_hours_cannot_be_reused_by_another_contract(self):
        assignment = self._approved_work()
        contracts = self.env['dct.security.contract']
        for number in (1, 2):
            contract = self.env['dct.security.contract'].create({'name': 'Hourly contract %s' % number,
                'company_id': self.company.id, 'partner_id': self.customer.id, 'site_ids': [Command.set(self.site.ids)],
                'date_start': '2026-01-01', 'date_end': '2026-12-31'})
            self.env['dct.security.contract.line'].create({'name': 'Approved service hours', 'contract_id': contract.id,
                'site_id': self.site.id, 'date_start': '2026-01-01', 'date_end': '2026-12-31',
                'billing_basis': 'hours', 'rate': 10, 'product_id': self.product.id})
            contract.action_activate()
            contracts |= contract
        first = self._billing(contract=contracts[0])
        first.action_approve()
        self.assertAlmostEqual(first.line_ids.quantity, assignment.approved_hours)
        second = self._billing(contract=contracts[1])
        with self.assertRaises(ValidationError):
            second.action_approve()

    def test_currency_mismatch_and_native_journal_conversion(self):
        foreign = self.env.ref('base.EUR') if self.company.currency_id != self.env.ref('base.EUR') else self.env.ref('base.USD')
        foreign.active = True
        self.env['res.currency.rate'].create({'currency_id': foreign.id, 'company_id': self.company.id, 'name': '2026-01-31', 'rate': 2})
        settings = self._compensation(currency_id=foreign.id)
        self.assertAlmostEqual(settings.estimated_hourly_cost, settings.currency_id.round(settings.rate / settings.monthly_hours))
        payroll = self._payroll()
        with self.assertRaises(UserError):
            payroll.action_calculate()
        payroll.currency_id = foreign
        payroll.action_review()
        payroll.action_approve()
        frozen_amount = payroll.net_amount
        payroll.action_create_entry()
        debit_line = payroll.move_id.line_ids.filtered(lambda r: r.debit > 0)
        expected_company = foreign._convert(frozen_amount, self.company.currency_id, self.company, date(2026, 1, 31))
        self.assertAlmostEqual(debit_line.debit, expected_company)
        self.assertAlmostEqual(debit_line.amount_currency, frozen_amount)
        self.assertEqual(debit_line.currency_id, foreign)
        self.assertFalse(payroll._fields['net_amount'].aggregator)
        with self.assertRaises(UserError):
            settings.with_user(self.finance).write({'rate': 1})
        with self.assertRaises(UserError):
            payroll.write({'currency_id': self.company.currency_id.id})

    def test_deductions_require_explicit_approval_reason(self):
        bill = self._billing()
        bill.write({'discount_percent': 10, 'deduction_amount': 100, 'deduction_product_id': self.product.id})
        with self.assertRaises(UserError):
            bill.action_approve()
        bill.adjustment_reason = 'Contract-approved service adjustment'
        bill.action_approve()
        self.assertAlmostEqual(bill.amount_total, 2690)
        self.assertEqual(bill.deduction_account_id, self.income)
        bill.action_create_invoice()
        self.assertAlmostEqual(bill.invoice_id.amount_untaxed, 2690)
        self._compensation()
        payroll = self._payroll(deduction_amount=100)
        with self.assertRaises(UserError):
            payroll.action_review()
        payroll.adjustment_reason = 'Guard-authorized documented deduction'
        payroll.action_review()
        payroll.action_approve()
        self.assertAlmostEqual(payroll.net_amount, 3310)

    def test_dashboard_cash_excludes_offsets_and_includes_settled_payment(self):
        report = self.env['dct.security.billing'].with_user(self.finance)

        def figures_for_company_currency():
            rows = report._dashboard_figures(self.company, '2026-01-01', '2026-12-31')
            return next((row for row in rows if row['currency_id'] == self.company.currency_id.id),
                        {'net': 0, 'outstanding': 0, 'cash_received': 0, 'estimated_cost': 0, 'estimated_margin': 0,
                         'invoice_ids': [], 'cash_move_ids': [], 'payroll_ids': []})

        baseline = figures_for_company_currency()
        bill = self._billing()
        bill.action_approve()
        bill.action_create_invoice()
        invoice = bill.invoice_id
        invoice.action_post()
        receivable_lines = invoice.line_ids.filtered(lambda line: line.account_id == self.receivable)
        offset = self.env['account.move'].create({'journal_id': self.pay_journal.id, 'company_id': self.company.id, 'date': '2026-01-31',
            'line_ids': [Command.create({'name': 'Non-cash offset', 'account_id': self.expense.id, 'debit': 100, 'credit': 0}),
                         Command.create({'name': 'Non-cash customer offset', 'account_id': self.receivable.id, 'partner_id': self.customer.id, 'debit': 0, 'credit': 100})]})
        offset.action_post()
        (receivable_lines | offset.line_ids.filtered(lambda line: line.account_id == self.receivable)).reconcile()
        before = figures_for_company_currency()
        self.assertAlmostEqual(before['net'] - baseline['net'], 3100)
        self.assertAlmostEqual(before['outstanding'] - baseline['outstanding'], 3000)
        self.assertAlmostEqual(before['cash_received'] - baseline['cash_received'], 0)
        bank = self.env['account.account'].create({'name': 'Test DCT Cash', 'code': 'DCT1200', 'account_type': 'asset_cash', 'company_ids': [Command.set(self.company.ids)]})
        bank_journal = self.env['account.journal'].create({'name': 'DCT Test Bank', 'code': 'DCTB', 'type': 'bank',
            'company_id': self.company.id, 'default_account_id': bank.id})
        method = bank_journal.inbound_payment_method_line_ids[:1]
        method.payment_account_id = bank
        payment = self.env['account.payment'].create({'payment_type': 'inbound', 'partner_type': 'customer', 'partner_id': self.customer.id,
            'amount': 500, 'currency_id': self.company.currency_id.id, 'journal_id': bank_journal.id, 'payment_method_line_id': method.id,
            'date': '2026-02-01', 'company_id': self.company.id})
        payment.action_post()
        (receivable_lines | payment.move_id.line_ids.filtered(lambda line: line.account_id == self.receivable)).reconcile()
        self.assertTrue(payment.is_matched)
        self._compensation()
        payroll = self._payroll()
        payroll.action_review()
        payroll.action_approve()
        figures = figures_for_company_currency()
        self.assertAlmostEqual(figures['cash_received'] - baseline['cash_received'], 500)
        self.assertAlmostEqual(figures['outstanding'] - baseline['outstanding'], 2500)
        self.assertAlmostEqual(figures['estimated_cost'] - baseline['estimated_cost'], 3410)
        self.assertAlmostEqual(figures['estimated_margin'] - baseline['estimated_margin'], -310)
        self.assertEqual(set(figures['invoice_ids']) - set(baseline['invoice_ids']), set(invoice.ids))
        self.assertEqual(set(figures['cash_move_ids']) - set(baseline['cash_move_ids']), set(payment.move_id.ids))
        self.assertEqual(set(figures['payroll_ids']) - set(baseline['payroll_ids']), set(payroll.ids))
        with self.assertRaises(AccessError):
            report.with_user(self.manager)._dashboard_figures(self.company, '2026-01-01', '2026-12-31')

    def test_rate_change_boundary_requires_split_and_calendar_proration(self):
        self._compensation(date_end='2026-01-15')
        self._compensation(date_start='2026-01-16', rate=6200)
        full = self._payroll()
        with self.assertRaises(UserError):
            full.action_calculate()
        full.unlink()
        first = self._payroll(date_end='2026-01-15')
        first.action_calculate()
        second = self._payroll(date_start='2026-01-16')
        second.action_calculate()
        self.assertAlmostEqual(first.gross_amount, 1500)
        self.assertAlmostEqual(second.gross_amount, 3200)
        self.assertAlmostEqual(_calendar_fraction(date(2026, 1, 16), date(2026, 2, 14)), 16 / 31 + 14 / 28)

    def test_site_local_day_handles_dst(self):
        self.site.tz = 'America/New_York'
        start, end = _utc_bounds(self.site, date(2026, 3, 8), date(2026, 3, 8))
        self.assertEqual((end - start).total_seconds() / 3600, 23)
        start, end = _utc_bounds(self.site, date(2026, 11, 1), date(2026, 11, 1))
        self.assertEqual((end - start).total_seconds() / 3600, 25)

    def test_financial_report_rendering_and_access(self):
        bill = self._billing()
        bill.action_approve()
        self._compensation()
        payroll = self._payroll()
        payroll.action_review()
        reports = self.env['ir.actions.report'].with_user(self.finance)
        for report_name, record, expected in [('report_billing', bill, self.contract.name), ('report_payroll', payroll, self.guard.name)]:
            html, _format = reports._render_qweb_html('dct_security_management.' + report_name, record.ids)
            self.assertIn(expected.encode(), html)
            self.assertIn(b'2026', html)
            with self.assertRaises(AccessError):
                self.env['ir.actions.report'].with_user(self.manager)._render_qweb_html('dct_security_management.' + report_name, record.ids)
