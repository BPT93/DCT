from datetime import datetime, timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from .common import SecurityCase


@tagged('post_install', '-at_install')
class TestPlanningAttendance(SecurityCase):

    def _shift(self, start='2031-06-02 05:00:00', end='2031-06-02 13:00:00', **values):
        vals = {'name': 'Day Guard Shift', 'site_id': self.site.id, 'post_id': self.post.id,
                'company_id': self.company.id, 'start': start, 'end': end, 'required_guards': 2}
        vals.update(values)
        return self.env['dct.security.shift'].create(vals)

    def _assign(self, shift, employee=None, **values):
        vals = {'shift_id': shift.id, 'employee_id': (employee or self.guard).id, 'company_id': self.company.id}
        vals.update(values)
        return self.env['dct.security.assignment'].create(vals)

    def _attendance(self, assignment, start=None, end=None):
        return self.env['hr.attendance'].create({'employee_id': assignment.employee_id.id,
                'check_in': start or assignment.start, 'check_out': end or assignment.end})

    def test_overlap_and_back_to_back(self):
        self.company.dct_rest_hours = 0
        first = self._shift()
        self._assign(first)
        conflict = self._shift('2031-06-02 12:00:00', '2031-06-02 20:00:00')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._assign(conflict)
        adjacent = self._shift('2031-06-02 13:00:00', '2031-06-02 21:00:00')
        self._assign(adjacent)

    def test_publish_frozen_and_rpc_transition(self):
        shift = self._shift()
        assignment = self._assign(shift)
        with self.assertRaises(AccessError):
            shift.write({'state': 'published'})
        with self.assertRaises(AccessError):
            assignment.write({'state': 'published'})
        shift.action_publish()
        shift.action_publish()
        self.assertEqual(assignment.state, 'published')
        with self.assertRaises(UserError):
            shift.write({'start': '2031-06-02 04:00:00'})

    def test_ineligible_and_site_authorization(self):
        shift = self._shift()
        self.guard.security_eligible = False
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._assign(shift)
        self.guard.security_eligible = True
        self.guard.security_site_ids = [Command.clear()]
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._assign(shift)

    def test_rest_override_requires_manager_reason(self):
        self._assign(self._shift())
        next_shift = self._shift('2031-06-02 14:00:00', '2031-06-02 22:00:00')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._assign(next_shift)
        assignment = self.env['dct.security.assignment'].with_user(self.manager).create({
            'shift_id': next_shift.id, 'employee_id': self.guard.id, 'company_id': self.company.id,
            'override_reason': 'Reviewed emergency coverage; approved by manager.'})
        self.assertTrue(assignment.override_reason)

    def test_overnight_generation_and_idempotency(self):
        template = self.env['dct.security.shift.template'].create({'name': 'Night', 'site_id': self.site.id,
            'post_id': self.post.id, 'company_id': self.company.id, 'start_hour': 20, 'end_hour': 8, 'required_guards': 2})
        wizard = self.env['dct.security.generate.roster'].create({'template_id': template.id,
            'date_from': '2031-01-31', 'date_to': '2031-02-01'})
        wizard.action_preview()
        self.assertEqual(len(wizard.line_ids), 2)
        wizard.action_generate()
        wizard.action_generate()
        shifts = self.env['dct.security.shift'].search([('template_id', '=', template.id)])
        self.assertEqual(len(shifts), 2)
        self.assertTrue(all(s.state == 'draft' and s.scheduled_hours == 12 for s in shifts))
        january = shifts.filtered(lambda s: s.local_date == fields.Date.to_date('2031-01-31'))
        self.assertEqual(january.end.date(), fields.Date.to_date('2031-02-01'))

    def test_dst_ambiguous_and_nonexistent_are_explicit(self):
        self.site.tz = 'America/New_York'
        template = self.env['dct.security.shift.template'].create({'name': 'DST', 'site_id': self.site.id,
            'post_id': self.post.id, 'company_id': self.company.id, 'start_hour': 2.5, 'end_hour': 8})
        wizard = self.env['dct.security.generate.roster'].create({'template_id': template.id,
            'date_from': '2026-03-08', 'date_to': '2026-03-08'})
        wizard.action_preview()
        self.assertEqual(wizard.line_ids.status, 'invalid')
        with self.assertRaises(UserError):
            wizard.action_generate()
        template.start_hour = 1.5
        wizard.write({'date_from': '2026-11-01', 'date_to': '2026-11-01'})
        wizard.action_preview()
        self.assertEqual(wizard.line_ids.status, 'invalid')

    def test_dst_duration_uses_actual_elapsed_time(self):
        self.site.tz = 'America/New_York'
        template = self.env['dct.security.shift.template'].create({'name': 'DST Overnight', 'site_id': self.site.id,
            'post_id': self.post.id, 'company_id': self.company.id, 'start_hour': 20, 'end_hour': 8})
        wizard = self.env['dct.security.generate.roster'].create({'template_id': template.id,
            'date_from': '2026-03-07', 'date_to': '2026-03-07'})
        wizard.action_preview()
        wizard.action_generate()
        shift = self.env['dct.security.shift'].search([('template_id', '=', template.id)])
        self.assertEqual(shift.scheduled_hours, 11)

    def test_replacement_preserves_history(self):
        shift = self._shift()
        old = self._assign(shift)
        shift.action_publish()
        wizard = self.env['dct.security.replace.guard'].create({'assignment_id': old.id,
            'employee_id': self.guard2.id, 'reason': 'Approved substitution'})
        wizard.action_replace()
        self.assertEqual(old.state, 'replaced')
        current = shift.assignment_ids.filtered(lambda a: a.state == 'published')
        self.assertEqual(current.employee_id, self.guard2)
        history = self.env['dct.security.replacement'].search([('old_assignment_id', '=', old.id)])
        self.assertEqual(history.new_assignment_id, current)
        with self.assertRaises(AccessError):
            history.write({'reason': 'Rewritten'})
        with self.assertRaises(UserError):
            wizard.action_replace()

    def test_partial_attendance_reconciliation_idempotent(self):
        shift = self._shift()
        assignment = self._assign(shift)
        shift.action_publish()
        self._attendance(assignment, '2031-06-02 05:15:00', '2031-06-02 09:00:00')
        self._attendance(assignment, '2031-06-02 09:30:00', '2031-06-02 12:30:00')
        assignment.action_reconcile_attendance()
        assignment.action_reconcile_attendance()
        self.assertEqual(len(assignment.allocation_ids), 2)
        self.assertEqual(assignment.worked_hours, 6.75)
        assignment.allocation_ids.action_approve()
        self.assertEqual(assignment.approved_hours, 6.75)
        self.assertEqual(assignment.approved_overtime_hours, 0)

    def test_no_duplicate_allocation_and_approval_freeze(self):
        shift = self._shift()
        assignment = self._assign(shift)
        shift.action_publish()
        attendance = self._attendance(assignment)
        assignment.action_reconcile_attendance()
        allocation = assignment.allocation_ids
        with self.assertRaises(ValidationError), self.cr.savepoint():
            allocation.copy({'start': assignment.start + timedelta(hours=1)})
        allocation.action_approve()
        allocation.action_approve()
        with self.assertRaises(UserError):
            attendance.write({'check_in': assignment.start - timedelta(minutes=15)})
        with self.assertRaises(UserError):
            allocation.write({'start': assignment.start + timedelta(minutes=15)})
        with self.assertRaises(AccessError):
            allocation.write({'state': 'draft'})

    def test_overtime_approved_separately(self):
        shift = self._shift()
        assignment = self._assign(shift)
        shift.action_publish()
        attendance = self._attendance(assignment, end=assignment.end + timedelta(hours=2))
        allocation = self.env['dct.security.allocation'].create({'assignment_id': assignment.id,
            'attendance_id': attendance.id, 'company_id': self.company.id, 'start': attendance.check_in, 'end': attendance.check_out})
        self.assertEqual(assignment.proposed_overtime_hours, 2)
        with self.assertRaises(UserError):
            assignment.action_approve_overtime()
        allocation.action_approve()
        assignment.action_approve_overtime()
        self.assertEqual(assignment.approved_overtime_hours, 2)

    def test_correction_audit_and_locked_period(self):
        shift = self._shift()
        assignment = self._assign(shift)
        shift.action_publish()
        attendance = self._attendance(assignment)
        assignment.action_reconcile_attendance()
        assignment.allocation_ids.action_approve()
        correction = self.env['dct.security.attendance.correction'].create({'attendance_id': attendance.id,
            'site_id': self.site.id, 'company_id': self.company.id, 'new_check_in': assignment.start - timedelta(minutes=5),
            'new_check_out': assignment.end, 'reason': 'Supervisor verified earlier check-in.'})
        correction.action_submit()
        correction.action_approve()
        self.assertEqual(correction.old_check_in, assignment.start)
        self.assertEqual(attendance.check_in, assignment.start - timedelta(minutes=5))
        self.assertEqual(assignment.allocation_ids.state, 'draft')
        assignment.allocation_ids.action_approve()
        period = self.env['dct.security.attendance.period'].create({'name': 'June approved', 'employee_id': self.guard.id,
            'company_id': self.company.id, 'start': '2031-06-01 00:00:00', 'end': '2031-07-01 00:00:00'})
        period.action_approve()
        with self.assertRaises(UserError):
            attendance.write({'check_out': assignment.end + timedelta(minutes=10)})
        with self.assertRaises(UserError), self.cr.savepoint():
            self._attendance(assignment, '2031-06-03 05:00:00', '2031-06-03 13:00:00')

    def test_attendance_presence_and_missing_checkout(self):
        shift = self._shift()
        assignment = self._assign(shift)
        shift.action_publish()
        attendance = self.env['hr.attendance'].create({'employee_id': self.guard.id, 'check_in': assignment.start})
        with patch('odoo.fields.Datetime.now', return_value=assignment.start + timedelta(hours=1)):
            assignment._compute_attendance_state()
            self.assertEqual(assignment.attendance_state, 'on_duty')
        with patch('odoo.fields.Datetime.now', return_value=assignment.end + timedelta(hours=3)):
            assignment._compute_attendance_state()
            self.assertEqual(assignment.attendance_state, 'missing_checkout')
        self.assertFalse(attendance.check_out)

    def test_suspected_absence_has_no_automatic_deduction(self):
        shift = self._shift()
        assignment = self._assign(shift)
        shift.action_publish()
        with patch('odoo.fields.Datetime.now', return_value=assignment.start + timedelta(hours=1)):
            assignment._compute_attendance_state()
            self.assertEqual(assignment.attendance_state, 'suspected_absence')
        self.assertEqual(assignment.approved_hours, 0)
        self.assertEqual(assignment.approved_overtime_hours, 0)

    def test_approved_leave_flags_existing_roster_and_blocks_new(self):
        shift = self._shift()
        assignment = self._assign(shift)
        shift.action_publish()
        leave_type = self.env['hr.leave.type'].create({'name': 'DCT Test Leave', 'requires_allocation': False,
            'leave_validation_type': 'no_validation'})
        leave = self.env['hr.leave'].create({'name': 'Approved leave test', 'employee_id': self.guard.id,
            'holiday_status_id': leave_type.id, 'request_date_from': '2031-06-02', 'request_date_to': '2031-06-02'})
        if leave.state != 'validate':
            leave.action_approve()
        assignment.invalidate_recordset(['leave_conflict'])
        self.assertEqual(leave.state, 'validate')
        self.assertTrue(assignment.leave_conflict)
        self.assertEqual(assignment.state, 'published')
        self.assertEqual(shift.assigned_guards, 0)

    def test_required_qualification_expiry(self):
        qualification = self.env['dct.security.qualification'].create({'name': 'First Aid', 'company_id': self.company.id})
        shift = self._shift(qualification_ids=[Command.link(qualification.id)])
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._assign(shift)
        self.env['dct.security.guard.qualification'].create({'employee_id': self.guard.id,
            'qualification_id': qualification.id, 'company_id': self.company.id, 'expiry_date': '2031-01-01'})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._assign(shift)

    def test_copy_week_is_idempotent(self):
        shift = self._shift()
        self._assign(shift)
        shift.action_publish()
        shift.action_copy_week()
        shift.action_copy_week()
        copied = self.env['dct.security.shift'].search([('generation_key', 'like', 'copy:%s:' % shift.id)])
        self.assertEqual(len(copied), 1)
        self.assertEqual(copied.state, 'draft')
        self.assertEqual(copied.start, shift.start + timedelta(days=7))
        self.assertEqual(len(copied.assignment_ids), 1)

    def test_supervisor_can_preview_generate_publish_and_record_attendance(self):
        supervisor = new_test_user(self.env, login='dct_planning_supervisor',
            groups='base.group_user,dct_security_management.group_supervisor', company_id=self.company.id)
        self.site.supervisor_ids = [Command.link(supervisor.id)]
        template = self.env['dct.security.shift.template'].create({'name': 'Supervisor Generation', 'site_id': self.site.id,
            'post_id': self.post.id, 'company_id': self.company.id, 'start_hour': 8, 'end_hour': 16})
        with self.assertRaises(AccessError):
            template.with_user(supervisor).write({'start_hour': 7})
        wizard = self.env['dct.security.generate.roster'].with_user(supervisor).create({'template_id': template.id,
            'date_from': '2031-06-02', 'date_to': '2031-06-02'})
        wizard.action_preview()
        wizard.action_preview()
        wizard.action_generate()
        wizard.action_generate()
        shift = self.env['dct.security.shift'].with_user(supervisor).search([('template_id', '=', template.id)])
        assignment = self.env['dct.security.assignment'].with_user(supervisor).create({
            'shift_id': shift.id, 'employee_id': self.guard.id, 'company_id': self.company.id})
        shift.action_publish()
        self.env['hr.attendance'].with_user(supervisor).create({'employee_id': self.guard.id,
            'check_in': assignment.start, 'check_out': assignment.end})
        assignment.action_reconcile_attendance()
        self.assertEqual(assignment.worked_hours, 8)
        with self.assertRaises(AccessError):
            assignment.allocation_ids.action_approve()
        assignment.allocation_ids.with_user(self.manager).action_approve()
        self.assertEqual(assignment.approved_hours, 8)

    def test_manager_actions_and_rpc_quantity_forgery_denied(self):
        shift = self._shift().with_user(self.manager)
        assignment = self.env['dct.security.assignment'].with_user(self.manager).create({
            'shift_id': shift.id, 'employee_id': self.guard.id, 'company_id': self.company.id})
        with self.assertRaises(AccessError):
            assignment.write({'approved_hours': 999})
        with self.assertRaises(AccessError):
            assignment.write({'approved_overtime_hours': 999})
        shift.action_publish()
        attendance = self.env['hr.attendance'].with_user(self.manager).create({'employee_id': self.guard.id,
            'check_in': assignment.start, 'check_out': assignment.end})
        assignment.action_reconcile_attendance()
        with self.assertRaises(AccessError):
            assignment.allocation_ids.write({'hours': 999})
        assignment.allocation_ids.action_approve()
        assignment.action_approve_overtime()
        with self.assertRaises(UserError):
            attendance.write({'check_out': assignment.end + timedelta(hours=1)})
        self.assertEqual(assignment.approved_hours, 8)

    def test_native_auto_checkout_does_not_invent_guard_events(self):
        self.company.auto_check_out = True
        attendance = self.env['hr.attendance'].create({'employee_id': self.guard.id,
            'check_in': fields.Datetime.now() - timedelta(days=2)})
        self.env['hr.attendance']._cron_auto_check_out()
        attendance.invalidate_recordset(['check_out'])
        self.assertFalse(attendance.check_out)
