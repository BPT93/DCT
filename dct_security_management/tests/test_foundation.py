from odoo import Command
from odoo.exceptions import AccessError, ValidationError, UserError
from odoo.tests import tagged
from odoo.tests.common import new_test_user
from .common import SecurityCase


@tagged('post_install', '-at_install', 'dct_security')
class TestFoundation(SecurityCase):
    def test_company_and_site_scope(self):
        supervisor = new_test_user(self.env, login='dct_test_supervisor', groups='base.group_user,dct_security_management.group_supervisor', company_id=self.company.id)
        self.site.supervisor_ids = [Command.link(supervisor.id)]
        other_site = self.env['dct.security.site'].create({'name':'Other Site', 'partner_id':self.customer.id})
        self.assertEqual(self.site.with_user(supervisor).name, self.site.name)
        with self.assertRaises(AccessError):
            other_site.with_user(supervisor).read(['name'])
        # Adding broad HR permissions cannot defeat the global site rule.
        supervisor.group_ids = [Command.link(self.env.ref('hr.group_hr_user').id)]
        isolated = self.env['hr.employee'].create({'name':'Other Guard','is_security_guard':True,'guard_code':'OTHER'})
        with self.assertRaises(AccessError):
            isolated.with_user(supervisor).read(['name'])
        self.assertTrue(self.guard.with_user(supervisor).read(['name']))

    def test_guard_code_and_coordinates(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['hr.employee'].create({'name':'No guard code','is_security_guard':True})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.site.latitude = 95

    def test_cross_company_post_rejected(self):
        other = self.env['res.company'].create({'name':'Other Security Company'})
        with self.assertRaises(UserError), self.cr.savepoint():
            self.env['dct.security.post'].create({'name':'Wrong Company','site_id':self.site.id,'company_id':other.id})

    def test_external_follower_blocked(self):
        with self.assertRaises(AccessError):
            self.site.message_subscribe([self.customer.id])

    def test_readonly_and_private_finance_action(self):
        reader = new_test_user(self.env, login='dct_test_reader', groups='base.group_user,dct_security_management.group_readonly', company_id=self.company.id)
        with self.assertRaises(AccessError):
            self.site.with_user(reader).write({'name':'Forbidden'})
        with self.assertRaises(AccessError):
            self.guard.with_user(reader).action_security_payroll()
