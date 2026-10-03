from datetime import timedelta
from unittest.mock import patch

from dateutil.relativedelta import relativedelta

from odoo import Command, fields
from odoo.tests import tagged

from .common import SecurityCase


@tagged('post_install', '-at_install')
class TestSecurityAutomation(SecurityCase):

    def _template(self, site=None, post=None, company=None):
        site, post, company = site or self.site, post or self.post, company or self.company
        return self.env['dct.security.shift.template'].with_company(company).create({
            'name': 'Automation Draft Template', 'company_id': company.id, 'site_id': site.id,
            'post_id': post.id, 'start_hour': 8, 'end_hour': 16,
            'auto_generate': True, 'generate_days': 2})

    def _dispatch(self):
        with patch('odoo.addons.dct_security_management.models.automation._logger.exception') as failure:
            self.env['dct.security.site']._cron_security_operations()
            failure.assert_not_called()

    def _contract(self):
        today = fields.Date.today()
        start = today.replace(day=1) - relativedelta(months=1)
        end = today + timedelta(days=3)
        product = self.env['product.product'].create({'name': 'Fictional Automation Security Service',
            'type': 'service', 'company_id': self.company.id, 'taxes_id': [Command.clear()]})
        contract = self.env['dct.security.contract'].create({'name': 'Automation Service Contract',
            'company_id': self.company.id, 'partner_id': self.customer.id, 'site_ids': [Command.set(self.site.ids)],
            'date_start': start, 'date_end': end, 'auto_billing': True})
        self.env['dct.security.contract.line'].create({'name': 'Fixed Monthly Coverage',
            'contract_id': contract.id, 'site_id': self.site.id, 'post_id': self.post.id,
            'date_start': start, 'date_end': end, 'billing_basis': 'fixed', 'rate': 1000,
            'product_id': product.id, 'required_guards': 2})
        contract.action_activate()
        return contract

    def test_company_opt_in_isolation_and_draft_generation(self):
        template = self._template()
        other = self.env['res.company'].create({'name': 'Fictional Disabled Automation Company',
            'dct_automation_enabled': False})
        customer = self.env['res.partner'].create({'name': 'Fictional Other Customer', 'company_id': other.id})
        site = self.env['dct.security.site'].with_company(other).create({'name': 'Other Automation Site',
            'partner_id': customer.id, 'company_id': other.id, 'tz': 'UTC'})
        post = self.env['dct.security.post'].with_company(other).create({'name': 'Other Gate',
            'site_id': site.id, 'company_id': other.id})
        other_template = self._template(site, post, other)
        self.company.dct_automation_enabled = False
        self._dispatch()
        self.assertFalse(self.env['dct.security.shift'].search([('template_id', 'in', [template.id, other_template.id])]))
        self.company.dct_automation_enabled = True
        self._dispatch()
        self._dispatch()
        shifts = self.env['dct.security.shift'].search([('template_id', '=', template.id)])
        self.assertEqual(len(shifts), 2)
        self.assertTrue(all(shift.state == 'draft' and not shift.assignment_ids for shift in shifts))
        self.assertFalse(self.env['dct.security.shift'].search([('template_id', '=', other_template.id)]))
        other.dct_automation_enabled = True
        # The per-company job must not process another enabled company.
        self.env['dct.security.shift.template'].with_company(self.company)._cron_generate_rosters()
        self.assertFalse(self.env['dct.security.shift'].search([('template_id', '=', other_template.id)]))
        self._dispatch()
        self.assertEqual(self.env['dct.security.shift'].search_count([('template_id', '=', other_template.id)]), 2)

    def test_attendance_exception_review_and_activity_deduplication(self):
        self.company.dct_automation_enabled = True
        now = fields.Datetime.now()
        shift = self.env['dct.security.shift'].create({'name': 'Automation Suspected Absence',
            'site_id': self.site.id, 'post_id': self.post.id, 'company_id': self.company.id,
            'start': now - timedelta(hours=2), 'end': now + timedelta(hours=6), 'required_guards': 1})
        assignment = self.env['dct.security.assignment'].create({'shift_id': shift.id,
            'employee_id': self.guard.id, 'company_id': self.company.id})
        shift.action_publish()
        self._dispatch()
        self._dispatch()
        exception = self.env['dct.security.attendance.exception'].search([('assignment_id', '=', assignment.id)])
        self.assertEqual(len(exception), 1)
        self.assertEqual(exception.kind, 'suspected_absence')
        self.assertEqual(len(exception.activity_ids), 1)
        exception.with_user(self.manager).resolution = 'Supervisor reviewed missing check-in and requested factual attendance evidence.'
        exception.with_user(self.manager).action_review()
        self.assertEqual(exception.state, 'reviewed')
        self.assertFalse(exception.activity_ids)
        self._dispatch()
        self.assertEqual(self.env['dct.security.attendance.exception'].search_count([('assignment_id', '=', assignment.id)]), 1)
        self.assertFalse(exception.activity_ids)
        self.assertFalse(assignment.allocation_ids)
        self.assertEqual(assignment.approved_hours, 0)
        self.assertFalse(self.env['hr.attendance'].search([('employee_id', '=', self.guard.id)]))

    def test_overdue_and_expiry_reminders_are_idempotent(self):
        self.company.dct_automation_enabled = True
        now = fields.Datetime.now()
        category = self.env['dct.security.incident.category'].create({'name': 'Automation Observation', 'company_id': self.company.id})
        incident = self.env['dct.security.incident'].create({'site_id': self.site.id, 'company_id': self.company.id,
            'category_id': category.id, 'description': 'Fictional overdue observation.',
            'deadline': fields.Date.today() - timedelta(days=1)})
        route = self.env['dct.security.patrol.route'].create({'name': 'Automation Route',
            'site_id': self.site.id, 'company_id': self.company.id,
            'checkpoint_ids': [Command.create({'name': 'Gate'})]})
        patrol = self.env['dct.security.patrol.round'].create({'route_id': route.id, 'site_id': self.site.id,
            'company_id': self.company.id, 'employee_id': self.guard.id,
            'planned_start': now - timedelta(hours=2), 'planned_end': now - timedelta(hours=1)})
        qualification_type = self.env['dct.security.qualification'].create({'name': 'Automation First Aid', 'company_id': self.company.id})
        qualification = self.env['dct.security.guard.qualification'].create({'employee_id': self.guard.id,
            'qualification_id': qualification_type.id, 'company_id': self.company.id,
            'expiry_date': fields.Date.today() + timedelta(days=3)})
        contract = self._contract()
        self._dispatch()
        first_ids = {record._name: record.activity_ids.ids for record in (incident, patrol, qualification, contract)}
        self._dispatch()
        for record in (incident, patrol, qualification, contract):
            self.assertEqual(len(record.activity_ids), 1, record._name)
            self.assertEqual(record.activity_ids.ids, first_ids[record._name])
            self.assertEqual(record.activity_ids.user_id, self.manager)
        self.assertEqual(patrol.state, 'draft')
        self.assertFalse(patrol.result_ids)
        self.assertEqual(incident.state, 'new')
        self.assertEqual(contract.state, 'active')

    def test_draft_billing_opt_in_and_no_automatic_approval(self):
        contract = self._contract()
        self.company.dct_automation_enabled = False
        self._dispatch()
        self.assertFalse(contract.billing_ids)
        self.company.dct_automation_enabled = True
        contract.auto_billing = False
        self._dispatch()
        self.assertFalse(contract.billing_ids)
        contract.auto_billing = True
        self._dispatch()
        self._dispatch()
        self.assertEqual(len(contract.billing_ids), 1)
        bill = contract.billing_ids
        expected_end = fields.Date.today().replace(day=1) - timedelta(days=1)
        self.assertEqual(bill.date_start, expected_end.replace(day=1))
        self.assertEqual(bill.date_end, expected_end)
        self.assertEqual(bill.state, 'draft')
        self.assertFalse(bill.invoice_id)
        self.assertFalse(bill.approved_by)
        self.assertFalse(bill.line_ids)
