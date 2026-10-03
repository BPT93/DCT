from odoo import Command
from odoo.tests.common import TransactionCase, new_test_user


class SecurityCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.customer = cls.env['res.partner'].create({'name': 'Fictional Security Test Customer', 'company_id': cls.company.id})
        cls.manager = new_test_user(cls.env, login='dct_ops_manager', groups='base.group_user,dct_security_management.group_manager', company_id=cls.company.id)
        cls.site = cls.env['dct.security.site'].create({'name': 'Test Gate Site', 'partner_id': cls.customer.id, 'company_id': cls.company.id, 'tz': 'Asia/Baghdad', 'supervisor_ids': [Command.link(cls.manager.id)]})
        cls.post = cls.env['dct.security.post'].create({'name': 'Main Gate', 'site_id': cls.site.id, 'company_id': cls.company.id})
        cls.guard = cls.env['hr.employee'].create({'name': 'Test Guard One', 'guard_code': 'TEST-001', 'is_security_guard': True, 'company_id': cls.company.id, 'security_site_ids': [Command.link(cls.site.id)]})
        cls.guard2 = cls.env['hr.employee'].create({'name': 'Test Guard Two', 'guard_code': 'TEST-002', 'is_security_guard': True, 'company_id': cls.company.id, 'security_site_ids': [Command.link(cls.site.id)]})
