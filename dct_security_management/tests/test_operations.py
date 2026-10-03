from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from .common import SecurityCase


@tagged('post_install', '-at_install')
class TestSecurityOperations(SecurityCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls.env['dct.security.incident.category'].create({'name': 'Access Control', 'company_id': cls.company.id})
        cls.route = cls.env['dct.security.patrol.route'].create({
            'name': 'Gate Inspection', 'site_id': cls.site.id, 'company_id': cls.company.id,
            'checkpoint_ids': [Command.create({'name': 'Gate', 'sequence': 10}), Command.create({'name': 'Fence', 'sequence': 20})],
        })
        cls.checklist = cls.env['dct.security.inspection.template'].create({
            'name': 'Site Standard', 'company_id': cls.company.id,
            'item_ids': [Command.create({'name': 'Gate secured'})],
        })

    def _incident(self):
        return self.env['dct.security.incident'].with_user(self.manager).create({
            'site_id': self.site.id, 'company_id': self.company.id,
            'category_id': self.category.id, 'description': 'Test observation',
        })

    def _patrol(self):
        now = fields.Datetime.now()
        return self.env['dct.security.patrol.round'].with_user(self.manager).create({
            'route_id': self.route.id, 'site_id': self.site.id, 'company_id': self.company.id,
            'employee_id': self.guard.id, 'planned_start': now, 'planned_end': now + timedelta(hours=1),
        })

    def test_incident_workflow_cannot_skip_or_write_state(self):
        incident = self._incident()
        with self.assertRaises(AccessError):
            incident.write({'state': 'closed'})
        with self.assertRaises(UserError):
            incident.action_close()
        incident.action_acknowledge()
        incident.action_investigate()
        with self.assertRaises(ValidationError):
            incident.action_resolve()
        incident.resolution = 'Gate mechanism repaired and checked.'
        incident.action_resolve()
        incident.action_close()
        with self.assertRaises(UserError):
            incident.description = 'Rewrite history'
        incident.reopen_reason = 'Follow-up evidence requires review.'
        incident.action_reopen()
        self.assertEqual(incident.state, 'investigating')
        self.assertFalse(incident.reopen_reason)

    def test_critical_activity_idempotent(self):
        incident = self._incident()
        incident.write({'severity': 'critical'})
        before = len(incident.activity_ids)
        incident.write({'severity': 'critical'})
        self.assertTrue(before)
        self.assertEqual(len(incident.activity_ids), before)

    def test_patrol_snapshots_and_required_checkpoints(self):
        patrol = self._patrol()
        patrol.action_start()
        first, second = patrol.result_ids.sorted('sequence')
        self.route.checkpoint_ids[0].name = 'Renamed future checkpoint'
        self.assertEqual(first.name, 'Gate')
        with self.assertRaises(UserError):
            second.action_complete()
        with self.assertRaises(UserError):
            patrol.action_close()
        first.notes = 'Manually checked by supervisor.'
        first.action_complete()
        with self.assertRaises(UserError):
            first.action_complete()
        second.exception_reason = 'Area closed for authorized maintenance.'
        second.action_approve_exception()
        patrol.action_close()
        self.assertEqual(patrol.state, 'closed')
        self.assertEqual(patrol.completion_percent, 50)
        self.assertEqual(second.exception_approved_by, self.manager)
        with self.assertRaises(AccessError):
            first.write({'completed_at': fields.Datetime.now()})
        with self.assertRaises(UserError):
            first.notes = 'Changed after closure'

    def test_supervisor_cannot_approve_patrol_exception(self):
        supervisor = new_test_user(self.env, login='dct_patrol_supervisor', groups='base.group_user,dct_security_management.group_supervisor', company_id=self.company.id)
        self.site.supervisor_ids = [Command.link(supervisor.id)]
        patrol = self._patrol()
        patrol.action_start()
        result = patrol.result_ids[0].with_user(supervisor)
        result.exception_reason = 'Request review'
        with self.assertRaises(AccessError):
            result.action_approve_exception()

    def test_inspection_creates_one_incident_and_freezes_results(self):
        visit = self.env['dct.security.visit'].with_user(self.manager).create({
            'site_id': self.site.id, 'company_id': self.company.id, 'supervisor_id': self.guard.id,
            'template_id': self.checklist.id, 'findings': 'Gate latch requires repair.',
            'incident_category_id': self.category.id,
        })
        visit.action_start()
        with self.assertRaises(UserError):
            visit.action_complete()
        visit.result_ids.write({'result': 'fail', 'notes': 'Latch damaged'})
        visit.action_complete()
        visit.action_create_incident()
        incident = visit.incident_id
        visit.action_create_incident()
        self.assertEqual(visit.incident_id, incident)
        self.assertEqual(visit.result_ids.actor_id, self.manager)
        with self.assertRaises(UserError):
            visit.result_ids.write({'result': 'pass'})

    def test_foreign_site_dashboard_and_operation_denied(self):
        supervisor = new_test_user(self.env, login='dct_scope_supervisor', groups='base.group_user,dct_security_management.group_supervisor', company_id=self.company.id)
        incident = self._incident()
        with self.assertRaises(AccessError):
            incident.with_user(supervisor).read(['description'])
        dashboard = self.env['dct.security.dashboard'].with_user(supervisor)
        with self.assertRaises(AccessError):
            dashboard.get_overview(site_id=self.site.id)
        self.assertFalse(dashboard.get_map()['sites'])

    def test_dashboard_card_matches_source_and_map_coordinates(self):
        incident = self._incident()
        dashboard = self.env['dct.security.dashboard'].with_user(self.manager)
        overview = dashboard.get_overview(site_id=self.site.id)
        for card in overview['cards']:
            if card['key'] == 'incidents':
                self.assertEqual(card['value'], self.env[card['action']['res_model']].with_user(self.manager).search_count(card['action']['domain']))
                self.assertIn(incident.id, self.env[card['action']['res_model']].search(card['action']['domain']).ids)
        self.assertFalse(overview['finance'])
        self.site.write({'has_coordinates': True, 'latitude': 0, 'longitude': 0})
        pin = next(s for s in dashboard.get_map()['sites'] if s['id'] == self.site.id)
        self.assertTrue(pin['has_coordinates'])
        self.assertEqual(pin['latitude'], 0)

    def test_operational_reports_and_finance_report_denial(self):
        incident = self._incident()
        patrol = self._patrol()
        patrol.action_start()
        visit = self.env['dct.security.visit'].with_user(self.manager).create({
            'site_id': self.site.id, 'company_id': self.company.id, 'supervisor_id': self.guard.id,
            'template_id': self.checklist.id,
        })
        visit.action_start()
        shift = self.env['dct.security.shift'].create({
            'name': 'Report Shift', 'company_id': self.company.id,
            'site_id': self.site.id, 'post_id': self.post.id,
            'start': '2026-10-01 05:00:00', 'end': '2026-10-01 13:00:00',
            'assignment_ids': [Command.create({'employee_id': self.guard.id})],
        })
        reports = [('report_incident', incident, b'Test observation'),
                   ('report_patrol', patrol, b'Gate'), ('report_visit', visit, b'Gate secured'),
                   ('report_coverage', shift, b'Test Gate Site'),
                   ('report_roster', shift.assignment_ids, b'Test Guard One'),
                   ('report_attendance', shift.assignment_ids, b'Test Guard One')]
        for report, record, expected in reports:
            with self.subTest(report=report):
                html, _format = self.env['ir.actions.report'].with_user(self.manager)._render_qweb_html('dct_security_management.' + report, record.ids)
                self.assertIn(expected, html)
                self.assertIn(b'Generated:', html)
        with self.assertRaises(AccessError):
            self.env['report.dct_security_management.payroll_document'].with_user(self.manager)._get_report_values([])
