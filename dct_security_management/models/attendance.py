from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain

_CORRECTION_TOKEN = object()
_NATIVE_POLICY_TOKEN = object()


class Allocation(models.Model):
    _name = 'dct.security.allocation'
    _description = 'Security Attendance Allocation'
    _inherit = ['dct.security.mixin']
    _order = 'start desc'

    assignment_id = fields.Many2one('dct.security.assignment', required=True, check_company=True, ondelete='restrict', index=True)
    attendance_id = fields.Many2one('hr.attendance', required=True, ondelete='restrict', index=True)
    employee_id = fields.Many2one(related='assignment_id.employee_id', store=True, index=True)
    site_id = fields.Many2one(related='assignment_id.site_id', store=True, index=True)
    start = fields.Datetime(required=True, index=True)
    end = fields.Datetime(required=True, index=True)
    hours = fields.Float(compute='_compute_hours', store=True, readonly=True)
    state = fields.Selection([('draft', 'Pending Review'), ('approved', 'Approved')], default='draft', readonly=True, required=True, copy=False, index=True)
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    note = fields.Text()

    @api.depends('start', 'end')
    def _compute_hours(self):
        for rec in self:
            # Allocations describe actual worked intervals; recorded breaks are separate check-out/in events.
            rec.hours = (rec.end - rec.start).total_seconds() / 3600 if rec.start and rec.end else 0

    @api.constrains('assignment_id', 'attendance_id', 'company_id', 'start', 'end')
    def _check_interval(self):
        self.assignment_id._lock_employees()
        self.flush_recordset(['employee_id', 'start', 'end'])
        for rec in self:
            raw = rec.attendance_id
            if rec.assignment_id.company_id != rec.company_id or rec.employee_id != raw.employee_id:
                raise ValidationError(_('Attendance, assignment, guard and company must match.'))
            if rec.assignment_id.state != 'published':
                raise ValidationError(_('Attendance allocations require a published assignment.'))
            if not raw.check_out or rec.start >= rec.end or rec.start < raw.check_in or rec.end > raw.check_out:
                raise ValidationError(_('An allocation must be a positive interval within completed raw attendance.'))
            if rec.end <= rec.assignment_id.start or rec.start >= rec.assignment_id.end:
                raise ValidationError(_('The allocated interval must overlap the assignment.'))
            self.env.cr.execute('SELECT id FROM dct_security_allocation WHERE employee_id=%s AND id<>%s AND start<%s AND "end">%s LIMIT 1', [rec.employee_id.id, rec.id, rec.end, rec.start])
            if self.env.cr.fetchone():
                raise ValidationError(_('The same worked time cannot be allocated more than once.'))
            self.env['dct.security.attendance.period']._check_unlocked(rec.employee_id, rec.start, rec.end)

    @api.model_create_multi
    def create(self, vals_list):
        if any(v.get('state', 'draft') != 'draft' or {'approved_by', 'approved_at', 'hours', 'employee_id', 'site_id'}.intersection(v) for v in vals_list):
            raise AccessError(_('Create allocations pending review, then approve.'))
        self.env['dct.security.assignment'].browse(sorted({v['assignment_id'] for v in vals_list if v.get('assignment_id')}))._lock_employees()
        return super().create(vals_list)

    def write(self, vals):
        if {'state', 'approved_by', 'approved_at', 'hours', 'employee_id', 'site_id'}.intersection(vals):
            raise AccessError(_('Use the allocation approval workflow.'))
        if any(rec.state == 'approved' for rec in self):
            raise UserError(_('Approved attendance is frozen. Request an attendance correction.'))
        return super().write(vals)

    def action_approve(self):
        self._check_role('group_manager', 'group_hr')
        self._lock()
        for rec in self:
            if rec.state == 'approved':
                continue
            rec._check_interval()
            super(Allocation, rec).write({'state': 'approved', 'approved_by': self.env.uid, 'approved_at': fields.Datetime.now()})
        return True

    def _check_consumed(self):
        # Use underlying relation tables only through authorized business models; scope is employee/company.
        if 'dct.security.payroll' in self.env.registry:
            fields_map = self.env['dct.security.payroll']._fields
            if 'allocation_ids' in fields_map:
                payroll = self.env['dct.security.payroll'].sudo().search_count([('allocation_ids', 'in', self.ids), ('state', 'in', ['approved', 'exported', 'accounted'])])
                if payroll:
                    raise UserError(_('Attendance used by approved payroll requires a separate payroll adjustment.'))
        if 'dct.security.billing.line' in self.env.registry:
            fields_map = self.env['dct.security.billing.line']._fields
            if 'allocation_ids' in fields_map:
                billed = self.env['dct.security.billing.line'].sudo().search_count([('allocation_ids', 'in', self.ids), ('billing_id.state', 'in', ['approved', 'invoiced'])])
                if billed:
                    raise UserError(_('Billed attendance requires the controlled credit and adjustment workflow.'))

    @api.ondelete(at_uninstall=False)
    def _unlink_pending_only(self):
        if any(rec.state == 'approved' for rec in self):
            raise UserError(_('Approved attendance allocations cannot be deleted.'))


class AttendancePeriod(models.Model):
    _name = 'dct.security.attendance.period'
    _description = 'Approved Attendance Period'
    _inherit = ['dct.security.mixin', 'mail.thread']

    name = fields.Char(required=True)
    employee_id = fields.Many2one('hr.employee', required=True, check_company=True, ondelete='restrict', index=True)
    start = fields.Datetime(required=True, index=True)
    end = fields.Datetime(required=True, index=True)
    state = fields.Selection([('draft', 'Draft'), ('approved', 'Locked')], required=True, default='draft', readonly=True, tracking=True)
    approved_by = fields.Many2one('res.users', readonly=True)
    approved_at = fields.Datetime(readonly=True)

    @api.constrains('start', 'end', 'employee_id', 'company_id')
    def _check_period(self):
        for rec in self:
            if rec.start >= rec.end or rec.employee_id.company_id != rec.company_id:
                raise ValidationError(_('Check the attendance period and employee company.'))

    @api.model
    def _check_unlocked(self, employee, start, end):
        employee_ids = employee.ids
        if not employee_ids or not start:
            return
        self.flush_model(['employee_id', 'start', 'end', 'state'])
        self.env.cr.execute('SELECT id FROM dct_security_attendance_period WHERE employee_id IN %s AND state=\'approved\' AND start<%s AND "end">%s LIMIT 1', [tuple(employee_ids), max(end or fields.Datetime.now(), start + timedelta(microseconds=1)), start])
        if self.env.cr.fetchone():
            raise UserError(_('This attendance period is locked. Use a separately approved financial adjustment; raw events remain unchanged.'))

    @api.model_create_multi
    def create(self, vals_list):
        if any(v.get('state', 'draft') != 'draft' or {'approved_by', 'approved_at'}.intersection(v) for v in vals_list):
            raise AccessError(_('Use the attendance period approval action.'))
        return super().create(vals_list)

    def write(self, vals):
        if {'state', 'approved_by', 'approved_at'}.intersection(vals) or any(rec.state == 'approved' for rec in self):
            raise AccessError(_('Approved attendance periods are immutable.'))
        return super().write(vals)

    def action_approve(self):
        self._check_role('group_manager', 'group_hr')
        self._lock()
        for rec in self:
            if rec.state == 'approved':
                continue
            self.env.cr.execute('SELECT id FROM hr_employee WHERE id=%s FOR UPDATE', [rec.employee_id.id])
            self.env.cr.execute('UPDATE hr_employee SET write_date=clock_timestamp() WHERE id=%s', [rec.employee_id.id])
            self._check_unlocked(rec.employee_id, rec.start, rec.end)
            allocations = self.env['dct.security.allocation'].search([('employee_id', '=', rec.employee_id.id), ('start', '<', rec.end), ('end', '>', rec.start)])
            if any(a.state != 'approved' for a in allocations):
                raise UserError(_('Review all attendance allocations before locking the period.'))
            self.env.cr.execute('SELECT id FROM hr_attendance WHERE employee_id=%s AND check_in<%s AND check_out IS NULL LIMIT 1', [rec.employee_id.id, rec.end])
            if self.env.cr.fetchone():
                raise UserError(_('An open attendance must be reviewed before this period is locked.'))
            super(AttendancePeriod, rec).write({'state': 'approved', 'approved_by': self.env.uid, 'approved_at': fields.Datetime.now()})
        return True

    @api.ondelete(at_uninstall=False)
    def _unlink_draft_only(self):
        if any(rec.state == 'approved' for rec in self):
            raise UserError(_('Locked attendance periods cannot be deleted.'))


class AttendanceCorrection(models.Model):
    _name = 'dct.security.attendance.correction'
    _description = 'Attendance Correction Request'
    _inherit = ['dct.security.mixin', 'mail.thread']
    _order = 'create_date desc'

    attendance_id = fields.Many2one('hr.attendance', required=True, ondelete='restrict')
    employee_id = fields.Many2one(related='attendance_id.employee_id', store=True)
    site_id = fields.Many2one('dct.security.site', required=True, check_company=True)
    old_check_in = fields.Datetime(readonly=True)
    old_check_out = fields.Datetime(readonly=True)
    new_check_in = fields.Datetime(required=True)
    new_check_out = fields.Datetime()
    reason = fields.Text(required=True)
    state = fields.Selection([('draft', 'Draft'), ('submitted', 'Submitted'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='draft', readonly=True, required=True, tracking=True)
    approved_by = fields.Many2one('res.users', readonly=True)
    approved_at = fields.Datetime(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('state', 'draft') != 'draft' or {'old_check_in', 'old_check_out', 'approved_by', 'approved_at'}.intersection(vals):
                raise AccessError(_('Use the attendance correction workflow.'))
            attendance = self.env['hr.attendance'].browse(vals['attendance_id'])
            attendance.check_access('read')
            vals.update({'old_check_in': attendance.check_in, 'old_check_out': attendance.check_out})
        return super().create(vals_list)

    @api.constrains('site_id', 'company_id', 'attendance_id', 'new_check_in', 'new_check_out', 'reason')
    def _check_correction(self):
        for rec in self:
            if not (rec.reason or '').strip():
                raise ValidationError(_('An attendance correction needs a meaningful reason.'))
            if rec.employee_id.company_id != rec.company_id or rec.site_id.company_id != rec.company_id:
                raise ValidationError(_('Correction site, employee and company must match.'))
            if rec.new_check_out and rec.new_check_in >= rec.new_check_out:
                raise ValidationError(_('The corrected check-out must follow check-in.'))
            if not self.env['dct.security.assignment'].search_count([('employee_id', '=', rec.employee_id.id), ('site_id', '=', rec.site_id.id), ('start', '<', rec.old_check_out or rec.old_check_in + timedelta(days=1)), ('end', '>', rec.old_check_in)]):
                raise ValidationError(_('The attendance must relate to an assignment at the correction site.'))

    def write(self, vals):
        if {'state', 'old_check_in', 'old_check_out', 'approved_by', 'approved_at', 'employee_id'}.intersection(vals) or any(rec.state != 'draft' for rec in self):
            raise AccessError(_('Submitted correction requests and audit values cannot be edited.'))
        if 'attendance_id' in vals:
            raise AccessError(_('Create a new request to correct another attendance.'))
        return super().write(vals)

    def action_submit(self):
        self._check_role('group_manager', 'group_supervisor', 'group_hr')
        for rec in self:
            if rec.state == 'draft':
                super(AttendanceCorrection, rec).write({'state': 'submitted'})
        return True

    def action_approve(self):
        self._check_role('group_manager', 'group_hr')
        self._lock()
        for rec in self:
            if rec.state == 'approved':
                continue
            if rec.state != 'submitted':
                raise UserError(_('Submit the correction before approval.'))
            attendance = rec.attendance_id
            self.env.cr.execute('SELECT id FROM hr_employee WHERE id=%s FOR UPDATE', [rec.employee_id.id])
            self.env.cr.execute('UPDATE hr_employee SET write_date=clock_timestamp() WHERE id=%s', [rec.employee_id.id])
            attendance.invalidate_recordset(['check_in', 'check_out'])
            if attendance.check_in != rec.old_check_in or attendance.check_out != rec.old_check_out:
                raise UserError(_('Raw attendance changed after this request. Create a new correction request.'))
            self.env['dct.security.attendance.period']._check_unlocked(rec.employee_id, min(rec.old_check_in, rec.new_check_in), max(rec.old_check_out or fields.Datetime.now(), rec.new_check_out or fields.Datetime.now()))
            allocations = self.env['dct.security.allocation'].search([('attendance_id', '=', attendance.id)])
            allocations._check_consumed()
            for allocation in allocations:
                if not rec.new_check_out or allocation.start < rec.new_check_in or allocation.end > rec.new_check_out:
                    raise UserError(_('The correction would invalidate existing allocations. Retain raw history and use a separate financial adjustment.'))
            super(Allocation, allocations).write({'state': 'draft', 'approved_by': False, 'approved_at': False})
            attendance.with_context(dct_correction_token=_CORRECTION_TOKEN).write({'check_in': rec.new_check_in, 'check_out': rec.new_check_out})
            from .planning import Assignment
            super(Assignment, allocations.assignment_id).write({'approved_overtime_hours': 0, 'overtime_approved_by': False, 'overtime_approved_at': False})
            super(AttendanceCorrection, rec).write({'state': 'approved', 'approved_by': self.env.uid, 'approved_at': fields.Datetime.now()})
            attendance.message_post(body=_('Approved attendance correction: %s', rec.reason))
        return True

    def action_reject(self):
        self._check_role('group_manager', 'group_hr')
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Only submitted corrections can be rejected.'))
            super(AttendanceCorrection, rec).write({'state': 'rejected'})
        return True

    @api.ondelete(at_uninstall=False)
    def _unlink_draft_only(self):
        if any(rec.state != 'draft' for rec in self):
            raise UserError(_('Submitted attendance correction history cannot be deleted.'))


class AttendanceException(models.Model):
    _name = 'dct.security.attendance.exception'
    _description = 'Attendance Exception Review'
    _inherit = ['dct.security.mixin', 'mail.thread', 'mail.activity.mixin']

    assignment_id = fields.Many2one('dct.security.assignment', required=True, check_company=True, ondelete='restrict', index=True)
    employee_id = fields.Many2one(related='assignment_id.employee_id', store=True)
    site_id = fields.Many2one(related='assignment_id.site_id', store=True)
    kind = fields.Selection([('suspected_absence', 'Suspected Absence'), ('missing_checkout', 'Missing Checkout'), ('leave_conflict', 'Approved Leave Conflict')], required=True)
    state = fields.Selection([('open', 'Needs Review'), ('reviewed', 'Reviewed')], default='open', required=True, readonly=True)
    resolution = fields.Text()
    reviewed_by = fields.Many2one('res.users', readonly=True)
    reviewed_at = fields.Datetime(readonly=True)
    _exception_unique = models.Constraint('UNIQUE(assignment_id,kind)', 'This assignment exception was already recorded.')

    @api.constrains('assignment_id', 'company_id')
    def _check_assignment_company(self):
        for rec in self:
            if rec.assignment_id.company_id != rec.company_id:
                raise ValidationError(_('The exception company must match its assignment.'))

    @api.model_create_multi
    def create(self, vals_list):
        if any(v.get('state', 'open') != 'open' or {'reviewed_by', 'reviewed_at'}.intersection(v) for v in vals_list):
            raise AccessError(_('Use the exception review workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        if {'state', 'reviewed_by', 'reviewed_at'}.intersection(vals) or any(r.state == 'reviewed' for r in self):
            raise AccessError(_('Reviewed exceptions are frozen.'))
        return super().write(vals)

    def action_review(self):
        self._check_role('group_manager', 'group_hr', 'group_supervisor')
        for rec in self:
            if not rec.resolution:
                raise UserError(_('Record the review outcome. No automatic payroll deduction is made.'))
            super(AttendanceException, rec).write({'state': 'reviewed', 'reviewed_by': self.env.uid, 'reviewed_at': fields.Datetime.now()})
            rec.activity_feedback(['mail.mail_activity_data_todo'])
        return True

    @api.model
    def _cron_attendance_exceptions(self):
        now = fields.Datetime.now()
        assignments = self.env['dct.security.assignment'].search([('company_id', '=', self.env.company.id), ('company_id.dct_automation_enabled', '=', True), ('state', '=', 'published'), ('start', '<=', now), ('end', '>=', now - timedelta(days=31))], limit=5000)
        for assignment in assignments:
            kind = 'leave_conflict' if assignment.leave_conflict else assignment.attendance_state
            if kind not in ('suspected_absence', 'missing_checkout', 'leave_conflict'):
                continue
            self.env.cr.execute('SELECT id FROM dct_security_assignment WHERE id=%s FOR UPDATE', [assignment.id])
            self.env.cr.execute('UPDATE dct_security_assignment SET write_date=clock_timestamp() WHERE id=%s', [assignment.id])
            if self.search_count([('assignment_id', '=', assignment.id), ('kind', '=', kind)]):
                continue
            exception = self.create({'assignment_id': assignment.id, 'kind': kind, 'company_id': assignment.company_id.id})
            for user in assignment.site_id.supervisor_ids:
                exception._activity_once(user, _('Review attendance exception'))


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    dct_allocation_ids = fields.One2many('dct.security.allocation', 'attendance_id', string='Security Allocations')
    dct_company_id = fields.Many2one(related='employee_id.company_id', store=True, index=True)

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):
        if self.env.context.get('dct_native_guard_exclusion') is _NATIVE_POLICY_TOKEN:
            domain = Domain(domain) & Domain('employee_id.is_security_guard', '=', False)
        return super()._search(domain, offset=offset, limit=limit, order=order, **kwargs)

    def _cron_auto_check_out(self):
        # Native Community policy may fabricate checkout times. Security guards
        # retain their raw event and receive a DCT missing-checkout exception.
        return super(HrAttendance, self.with_context(dct_native_guard_exclusion=_NATIVE_POLICY_TOKEN))._cron_auto_check_out()

    def _cron_absence_detection(self):
        # Native technical absence events must not masquerade as guard evidence.
        return super(HrAttendance, self.with_context(dct_native_guard_exclusion=_NATIVE_POLICY_TOKEN))._cron_absence_detection()

    @api.model_create_multi
    def create(self, vals_list):
        employee_ids = sorted({v.get('employee_id') for v in vals_list if v.get('employee_id')})
        if employee_ids:
            self.env.cr.execute('SELECT id FROM hr_employee WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(employee_ids)])
            self.env.cr.execute('UPDATE hr_employee SET write_date=clock_timestamp() WHERE id IN %s', [tuple(employee_ids)])
        for vals in vals_list:
            employee = self.env['hr.employee'].browse(vals.get('employee_id'))
            if employee.is_security_guard:
                self.env['dct.security.attendance.period']._check_unlocked(employee, fields.Datetime.to_datetime(vals.get('check_in')) or fields.Datetime.now(), fields.Datetime.to_datetime(vals.get('check_out')) or fields.Datetime.now())
        return super().create(vals_list)

    def write(self, vals):
        if {'employee_id', 'check_in', 'check_out'}.intersection(vals):
            guards = self.employee_id.filtered('is_security_guard')
            new_employee = self.env['hr.employee'].browse(vals.get('employee_id'))
            if new_employee.is_security_guard:
                guards |= new_employee
            if guards:
                self.env.cr.execute('SELECT id FROM hr_employee WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(guards.ids))])
                self.env.cr.execute('UPDATE hr_employee SET write_date=clock_timestamp() WHERE id IN %s', [tuple(sorted(guards.ids))])
            for attendance in self.filtered(lambda a: a.employee_id.is_security_guard):
                start = min(attendance.check_in, fields.Datetime.to_datetime(vals.get('check_in')) or attendance.check_in)
                end = max(attendance.check_out or fields.Datetime.now(), fields.Datetime.to_datetime(vals.get('check_out')) or fields.Datetime.now())
                self.env['dct.security.attendance.period']._check_unlocked(attendance.employee_id, start, end)
                if attendance.dct_allocation_ids.filtered(lambda a: a.state == 'approved') and self.env.context.get('dct_correction_token') is not _CORRECTION_TOKEN:
                    raise UserError(_('Approved allocated attendance requires a correction request.'))
                if attendance.dct_allocation_ids and 'employee_id' in vals:
                    raise UserError(_('Allocated attendance cannot be transferred to another guard.'))
            if new_employee.is_security_guard:
                for attendance in self:
                    self.env['dct.security.attendance.period']._check_unlocked(new_employee,
                        fields.Datetime.to_datetime(vals.get('check_in')) or attendance.check_in,
                        fields.Datetime.to_datetime(vals.get('check_out')) or attendance.check_out or fields.Datetime.now())
        result = super().write(vals)
        if {'check_in', 'check_out'}.intersection(vals):
            self.dct_allocation_ids._check_interval()
        return result

    @api.ondelete(at_uninstall=False)
    def _unlink_security_attendance(self):
        for attendance in self.filtered(lambda a: a.employee_id.is_security_guard):
            self.env['dct.security.attendance.period']._check_unlocked(attendance.employee_id, attendance.check_in, attendance.check_out or fields.Datetime.now())
            if attendance.dct_allocation_ids:
                raise UserError(_('Allocated attendance is historical evidence and cannot be deleted.'))


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):
        if self.env.context.get('dct_native_guard_exclusion') is _NATIVE_POLICY_TOKEN:
            domain = Domain(domain) & Domain('is_security_guard', '=', False)
        return super()._search(domain, offset=offset, limit=limit, order=order, **kwargs)
