import base64
from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import new_test_user
from .common import SecurityCase


@tagged('post_install', '-at_install')
class TestSecurityBoundaries(SecurityCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.supervisor = new_test_user(cls.env, login='dct_scope_supervisor', groups='base.group_user,base.group_allow_export,dct_security_management.group_supervisor', company_id=cls.company.id)
        cls.site.supervisor_ids = [Command.link(cls.supervisor.id)]
        cls.other_site = cls.env['dct.security.site'].create({'name':'Restricted Site','partner_id':cls.customer.id})
        cls.category = cls.env['dct.security.incident.category'].create({'name':'Test category'})
        cls.incident = cls.env['dct.security.incident'].create({'site_id':cls.other_site.id,'category_id':cls.category.id,'description':'Confidential other-site incident'})

    def test_direct_read_export_aggregate_attachment_and_chatter(self):
        scoped = self.incident.with_user(self.supervisor)
        with self.assertRaises(AccessError):
            scoped.read(['description'])
        with self.assertRaises(AccessError):
            scoped.export_data(['description'])
        self.assertEqual(self.env['dct.security.incident'].with_user(self.supervisor)._read_group([('id','=',self.incident.id)],[],['__count']), [(0,)])
        attachment = self.env['ir.attachment'].create({'name':'restricted.txt','res_model':self.incident._name,'res_id':self.incident.id,'datas':base64.b64encode(b'confidential')})
        with self.assertRaises(AccessError):
            attachment.with_user(self.supervisor).read(['datas'])
        with self.assertRaises(AccessError):
            self.incident.message_subscribe(self.supervisor.partner_id.ids)
        with self.assertRaises(AccessError), self.cr.savepoint():
            attachment.write({'public':True})

    def test_dashboard_scope_and_company_forgery(self):
        dashboard = self.env['dct.security.dashboard'].with_user(self.supervisor)
        overview = dashboard.get_overview('2026-01-01','2026-01-31')
        self.assertEqual({s['id'] for s in overview['sites']}, {self.site.id})
        self.assertFalse(overview['finance'])
        with self.assertRaises(AccessError):
            dashboard.get_overview(site_id=self.other_site.id)
        company2 = self.env['res.company'].create({'name':'Isolated company'})
        with self.assertRaises(AccessError):
            dashboard.get_overview(company_id=company2.id)
        self.assertFalse(self.env['dct.security.site'].with_user(self.supervisor).search([('company_id','=',company2.id)]))

    def test_guard_manager_without_broad_hr_permission(self):
        guard = self.env['hr.employee'].with_user(self.manager).create({'name':'Manager Created Guard','is_security_guard':True,'guard_code':'MGR001','company_id':self.company.id,'security_site_ids':[Command.link(self.site.id)]})
        self.assertEqual(guard.guard_code,'MGR001')
        with self.assertRaises(AccessError):
            guard.read(['private_phone'])
        with self.assertRaises(AccessError):
            self.env['hr.employee'].with_user(self.manager).create({'name':'Forbidden private values','is_security_guard':True,'guard_code':'FORBIDDEN','private_phone':'123'})
        with self.assertRaises(AccessError):
            self.env['hr.version'].with_user(self.manager).search([])

    def test_two_companies_and_two_supervisors_keep_separate_records(self):
        second_supervisor = new_test_user(
            self.env, login='dct_second_site_supervisor',
            groups='base.group_user,dct_security_management.group_supervisor',
            company_id=self.company.id)
        self.other_site.supervisor_ids = [Command.link(second_supervisor.id)]
        self.assertTrue(self.incident.with_user(second_supervisor).read(['description']))
        with self.assertRaises(AccessError):
            self.site.with_user(second_supervisor).read(['name'])
        with self.assertRaises(AccessError):
            self.incident.with_user(self.supervisor).action_acknowledge()

        company = self.env['res.company'].create({'name': 'Second Security Company'})
        other_manager = new_test_user(
            self.env, login='dct_other_company_manager',
            groups='base.group_user,base.group_allow_export,dct_security_management.group_manager',
            company_id=company.id, company_ids=[Command.set(company.ids)])
        customer = self.env['res.partner'].create({'name': 'Second Company Customer', 'company_id': company.id})
        site = self.env['dct.security.site'].with_company(company).create({
            'name': 'Second Company Site', 'partner_id': customer.id, 'company_id': company.id})
        guard = self.env['hr.employee'].with_company(company).create({
            'name': 'Second Company Guard', 'is_security_guard': True, 'guard_code': 'OTHER-COMPANY',
            'company_id': company.id, 'security_site_ids': [Command.link(site.id)]})
        self.assertTrue(site.with_user(other_manager).with_context(allowed_company_ids=company.ids).read(['name']))
        self.assertTrue(guard.with_user(other_manager).with_context(allowed_company_ids=company.ids).read(['guard_code']))
        with self.assertRaises(AccessError):
            site.with_user(self.manager).read(['name'])
        with self.assertRaises(AccessError):
            self.site.with_user(other_manager).with_context(allowed_company_ids=company.ids).export_data(['name'])
        overview = self.env['dct.security.dashboard'].with_user(other_manager).with_context(
            allowed_company_ids=company.ids).get_overview('2026-01-01', '2026-01-31')
        self.assertEqual({row['id'] for row in overview['sites']}, {site.id})
        self.assertFalse(self.env['hr.employee'].with_user(self.manager).search([('id', '=', guard.id)]))

    def test_qualification_document_field_permission(self):
        kind = self.env['dct.security.qualification'].create({'name':'Training'})
        qualification = self.env['dct.security.guard.qualification'].create({'employee_id':self.guard.id,'qualification_id':kind.id,'expiry_date':'2027-01-01','certificate':base64.b64encode(b'private certificate')})
        with self.assertRaises(AccessError):
            qualification.with_user(self.supervisor).read(['certificate'])

    def test_report_finance_authorization(self):
        for report in ('report_payroll','report_billing'):
            action = self.env.ref('dct_security_management.'+report).with_user(self.supervisor)
            with self.assertRaises(AccessError):
                action._render_qweb_html(action.report_name, [])
