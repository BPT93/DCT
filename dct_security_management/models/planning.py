from datetime import timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

_REPLACEMENT_TOKEN = object()

class ResCompany(models.Model):
    _inherit = 'res.company'

    dct_rest_hours = fields.Float(default=8, string='Minimum rest hours')
    dct_max_shift_hours = fields.Float(default=12, string='Maximum shift hours')
    dct_absence_grace_minutes = fields.Integer(default=30, string='Suspected absence grace (minutes)')
    dct_checkout_grace_hours = fields.Float(default=2, string='Missing checkout grace (hours)')

    @api.constrains('dct_rest_hours', 'dct_max_shift_hours', 'dct_absence_grace_minutes', 'dct_checkout_grace_hours')
    def _check_dct_policy(self):
        for company in self:
            if min(company.dct_rest_hours, company.dct_max_shift_hours, company.dct_absence_grace_minutes, company.dct_checkout_grace_hours) < 0:
                raise ValidationError(_('Attendance and working-time policies must be nonnegative.'))


class ShiftTemplate(models.Model):
    _name = 'dct.security.shift.template'
    _description = 'Security Shift Template'
    _inherit = ['dct.security.mixin']

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    site_id = fields.Many2one('dct.security.site', required=True, check_company=True, ondelete='restrict', index=True)
    post_id = fields.Many2one('dct.security.post', required=True, check_company=True, ondelete='restrict')
    start_hour = fields.Float(default=8, required=True)
    end_hour = fields.Float(default=20, required=True)
    break_hours = fields.Float(default=0)
    required_guards = fields.Integer(default=1, required=True)
    qualification_ids = fields.Many2many('dct.security.qualification')
    weekday_ids = fields.Char(default='0,1,2,3,4,5,6', required=True, help='Monday=0 through Sunday=6, comma separated.')
    auto_generate = fields.Boolean(string='Generate drafts automatically')
    generate_days = fields.Integer(default=7)

    @api.constrains('site_id', 'post_id', 'company_id', 'start_hour', 'end_hour', 'required_guards', 'break_hours', 'weekday_ids', 'generate_days')
    def _check_template(self):
        for rec in self:
            if rec.site_id.company_id != rec.company_id or rec.post_id.site_id != rec.site_id:
                raise ValidationError(_('The template site, post and company must match.'))
            if not 0 <= rec.start_hour < 24 or not 0 <= rec.end_hour < 24 or rec.required_guards < 1 or rec.break_hours < 0 or rec.generate_days not in range(1, 367):
                raise ValidationError(_('Check template hours, coverage, breaks and generation horizon.'))
            try:
                weekdays = [int(value.strip()) for value in rec.weekday_ids.split(',')]
                if not weekdays or any(day not in range(7) for day in weekdays):
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValidationError(_('Weekdays must be comma-separated numbers from 0 to 6.'))

    @api.model
    def _cron_generate_rosters(self):
        import logging
        logger = logging.getLogger(__name__)
        for template in self.search([('auto_generate', '=', True), ('company_id', '=', self.env.company.id), ('company_id.dct_automation_enabled', '=', True)], limit=200):
            try:
                with self.env.cr.savepoint():
                    today = fields.Date.context_today(template.with_context(tz=template.site_id.tz or 'UTC'))
                    wizard = self.env['dct.security.generate.roster'].create({
                        'template_id': template.id, 'date_from': today,
                        'date_to': today + timedelta(days=template.generate_days - 1),
                    })
                    wizard.action_preview()
                    wizard.action_generate()
            except Exception:
                logger.exception('DCT roster generation failed for template %s', template.id)


class Shift(models.Model):
    _name = 'dct.security.shift'
    _description = 'Security Shift Slot'
    _inherit = ['dct.security.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'start desc, id desc'

    name = fields.Char(required=True)
    site_id = fields.Many2one('dct.security.site', required=True, check_company=True, ondelete='restrict', index=True)
    post_id = fields.Many2one('dct.security.post', required=True, check_company=True, ondelete='restrict', index=True)
    start = fields.Datetime(required=True, index=True, tracking=True)
    end = fields.Datetime(required=True, index=True, tracking=True)
    local_date = fields.Date(compute='_compute_hours', store=True, index=True, help='Local start date owns an overnight shift.')
    required_guards = fields.Integer(default=1, required=True, tracking=True)
    break_hours = fields.Float(default=0)
    qualification_ids = fields.Many2many('dct.security.qualification')
    state = fields.Selection([('draft', 'Draft'), ('published', 'Published'), ('cancelled', 'Cancelled')], default='draft', required=True, readonly=True, tracking=True, index=True)
    assignment_ids = fields.One2many('dct.security.assignment', 'shift_id')
    scheduled_hours = fields.Float(compute='_compute_hours', store=True)
    assigned_guards = fields.Integer(compute='_compute_coverage', store=True)
    missing_guards = fields.Integer(compute='_compute_coverage', store=True)
    template_id = fields.Many2one('dct.security.shift.template', ondelete='restrict', readonly=True)
    generation_key = fields.Char(readonly=True, copy=False, index=True)
    _generation_unique = models.Constraint('UNIQUE(generation_key)', 'This shift was already generated.')

    @api.depends('start', 'end', 'break_hours', 'site_id.tz')
    def _compute_hours(self):
        for rec in self:
            rec.scheduled_hours = max(0, (rec.end - rec.start).total_seconds() / 3600 - rec.break_hours) if rec.start and rec.end else 0
            rec.local_date = pytz.utc.localize(rec.start).astimezone(pytz.timezone(rec.site_id.tz or 'UTC')).date() if rec.start else False

    @api.depends('required_guards', 'assignment_ids.state', 'assignment_ids.leave_conflict')
    def _compute_coverage(self):
        for rec in self:
            rec.assigned_guards = len(rec.assignment_ids.filtered(lambda a: a.state in ('draft', 'published') and not a.leave_conflict))
            rec.missing_guards = max(0, rec.required_guards - rec.assigned_guards)

    @api.constrains('site_id', 'post_id', 'company_id', 'start', 'end', 'required_guards', 'break_hours')
    def _check_shift(self):
        for rec in self:
            if rec.site_id.company_id != rec.company_id or rec.post_id.site_id != rec.site_id:
                raise ValidationError(_('Shift site, post and company must match.'))
            if rec.start >= rec.end or rec.required_guards < 1 or rec.break_hours < 0 or rec.break_hours >= (rec.end - rec.start).total_seconds() / 3600:
                raise ValidationError(_('A shift needs a positive duration, coverage and a break shorter than its duration.'))
        self.assignment_ids._validate_assignment()

    @api.model_create_multi
    def create(self, vals_list):
        if any(values.get('state', 'draft') != 'draft' or {'local_date', 'scheduled_hours', 'assigned_guards', 'missing_guards'}.intersection(values) for values in vals_list):
            raise AccessError(_('Create shifts as drafts, then publish them.'))
        return super().create(vals_list)

    def write(self, vals):
        if {'state', 'local_date', 'scheduled_hours', 'assigned_guards', 'missing_guards'}.intersection(vals):
            raise AccessError(_('Use shift workflow actions to change state.'))
        frozen = {'start', 'end', 'company_id', 'site_id', 'post_id', 'required_guards', 'break_hours', 'qualification_ids', 'template_id', 'generation_key'}
        if frozen.intersection(vals) and any(rec.state != 'draft' for rec in self):
            raise UserError(_('Published schedules are historical records. Cancel and create a new draft.'))
        return super().write(vals)

    def action_publish(self):
        self._check_role('group_manager', 'group_supervisor')
        self._lock()
        for rec in self:
            if rec.state == 'published':
                continue
            if rec.state != 'draft':
                raise UserError(_('Only a draft shift can be published.'))
            rec.assignment_ids.filtered(lambda a: a.state == 'draft')._publish()
            super(Shift, rec).write({'state': 'published'})
        return True

    def action_cancel(self):
        self._check_role('group_manager', 'group_supervisor')
        self._lock()
        if self.assignment_ids.allocation_ids:
            raise UserError(_('A shift with recorded attendance cannot be cancelled.'))
        for rec in self:
            super(Assignment, rec.assignment_ids.filtered(lambda a: a.state in ('draft', 'published'))).write({'state': 'cancelled'})
            super(Shift, rec).write({'state': 'cancelled'})
        return True

    def action_copy_week(self):
        self._check_role('group_manager', 'group_supervisor')
        copies = self.browse()
        for rec in self:
            tz = pytz.timezone(rec.site_id.tz or 'UTC')
            vals = {}
            for field in ('start', 'end'):
                local = pytz.utc.localize(rec[field]).astimezone(tz).replace(tzinfo=None) + timedelta(days=7)
                try:
                    vals[field] = tz.localize(local, is_dst=None).astimezone(pytz.utc).replace(tzinfo=None)
                except (pytz.AmbiguousTimeError, pytz.NonExistentTimeError):
                    raise UserError(_('The copied week crosses an ambiguous or nonexistent local time. Create that shift explicitly.'))
            vals.update({'state': 'draft', 'assignment_ids': [], 'generation_key': 'copy:%s:%s' % (rec.id, vals['start']), 'template_id': False})
            existing = self.search([('generation_key', '=', vals['generation_key'])], limit=1)
            if not existing:
                existing = rec.copy(vals)
                for assignment in rec.assignment_ids.filtered(lambda a: a.state in ('draft', 'published')):
                    assignment.copy({'shift_id': existing.id, 'state': 'draft', 'override_reason': False})
            copies |= existing
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'view_mode': 'list,form', 'domain': [('id', 'in', copies.ids)]}

    @api.ondelete(at_uninstall=False)
    def _unlink_draft_only(self):
        if any(rec.state != 'draft' for rec in self):
            raise UserError(_('Only draft shifts can be deleted.'))


class Assignment(models.Model):
    _name = 'dct.security.assignment'
    _description = 'Individual Guard Assignment'
    _inherit = ['dct.security.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'start desc, id desc'

    shift_id = fields.Many2one('dct.security.shift', required=True, check_company=True, ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', required=True, check_company=True, ondelete='restrict', index=True)
    site_id = fields.Many2one(related='shift_id.site_id', store=True, index=True)
    start = fields.Datetime(related='shift_id.start', store=True, index=True)
    end = fields.Datetime(related='shift_id.end', store=True, index=True)
    name = fields.Char(compute='_compute_name', store=True)
    state = fields.Selection([('draft', 'Draft'), ('published', 'Published'), ('replaced', 'Replaced'), ('cancelled', 'Cancelled')], default='draft', required=True, readonly=True, tracking=True, copy=False, index=True)
    leave_conflict = fields.Boolean(readonly=True, copy=False)
    override_reason = fields.Text(copy=False, help='Manager-only documented override of minimum rest / maximum hours.')
    allocation_ids = fields.One2many('dct.security.allocation', 'assignment_id', copy=False)
    scheduled_hours = fields.Float(related='shift_id.scheduled_hours', store=True)
    worked_hours = fields.Float(compute='_compute_worked_hours', store=True)
    approved_hours = fields.Float(compute='_compute_worked_hours', store=True)
    proposed_overtime_hours = fields.Float(compute='_compute_worked_hours', store=True)
    approved_overtime_hours = fields.Float(readonly=True, copy=False)
    overtime_approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    overtime_approved_at = fields.Datetime(readonly=True, copy=False)
    attendance_state = fields.Selection([('scheduled', 'Scheduled'), ('on_duty', 'On Duty'), ('off_duty', 'Off Duty'), ('on_leave', 'On Leave'), ('late', 'Late / Not Checked In'), ('missing_checkout', 'Missing Checkout'), ('suspected_absence', 'Suspected Absence')], compute='_compute_attendance_state')
    lateness_minutes = fields.Float(compute='_compute_attendance_state')
    early_departure_minutes = fields.Float(compute='_compute_attendance_state')

    @api.depends('employee_id.name', 'shift_id.name')
    def _compute_name(self):
        for rec in self:
            rec.name = '%s — %s' % (rec.employee_id.name or '', rec.shift_id.name or '')

    @api.depends('allocation_ids.hours', 'allocation_ids.state', 'scheduled_hours')
    def _compute_worked_hours(self):
        for rec in self:
            rec.worked_hours = sum(rec.allocation_ids.mapped('hours'))
            rec.approved_hours = sum(rec.allocation_ids.filtered(lambda a: a.state == 'approved').mapped('hours'))
            rec.proposed_overtime_hours = max(0, rec.worked_hours - rec.scheduled_hours)

    def _compute_attendance_state(self):
        now = fields.Datetime.now()
        active = self.filtered(lambda a: a.state == 'published' and a.start and a.end)
        attendance_by_employee = {}
        if active:
            attendance_records = self.env['hr.attendance'].search([('employee_id', 'in', active.employee_id.ids), ('check_in', '<', max(active.mapped('end'))), '|', ('check_out', '=', False), ('check_out', '>', min(active.mapped('start')))], order='check_in')
            for attendance_record in attendance_records:
                attendance_by_employee.setdefault(attendance_record.employee_id.id, self.env['hr.attendance'])
                attendance_by_employee[attendance_record.employee_id.id] |= attendance_record
        for rec in self:
            rec.lateness_minutes = rec.early_departure_minutes = 0
            rec.attendance_state = 'off_duty'
            if rec.state != 'published':
                continue
            if rec.leave_conflict:
                rec.attendance_state = 'on_leave'
                continue
            attendance = attendance_by_employee.get(rec.employee_id.id, self.env['hr.attendance']).filtered(lambda a: a.check_in < rec.end and (not a.check_out or a.check_out > rec.start))
            if attendance:
                rec.lateness_minutes = max(0, (attendance[0].check_in - rec.start).total_seconds() / 60)
                closed = attendance.filtered('check_out')
                if closed and now >= rec.end:
                    rec.early_departure_minutes = max(0, (rec.end - max(closed.mapped('check_out'))).total_seconds() / 60)
            open_records = attendance.filtered(lambda a: not a.check_out)
            if open_records and (now > rec.end + timedelta(hours=rec.company_id.dct_checkout_grace_hours) or any(now - a.check_in > timedelta(hours=rec.company_id.dct_max_open_hours) for a in open_records)):
                rec.attendance_state = 'missing_checkout'
            elif rec.start <= now < rec.end and attendance.filtered(lambda a: a.check_in <= now and (not a.check_out or a.check_out > now)):
                rec.attendance_state = 'on_duty'
            elif now < rec.start:
                rec.attendance_state = 'scheduled'
            elif not attendance and now > rec.start + timedelta(minutes=rec.company_id.dct_absence_grace_minutes):
                rec.attendance_state = 'suspected_absence'
            elif not attendance:
                rec.attendance_state = 'late'

    def _lock_employees(self):
        ids = sorted(self.employee_id.ids)
        if ids:
            self.env.cr.execute('SELECT id FROM hr_employee WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(ids)])
            self.env.cr.execute('UPDATE hr_employee SET write_date=clock_timestamp() WHERE id IN %s', [tuple(ids)])

    def _validate_assignment(self):
        self._lock_employees()
        self.flush_recordset(['employee_id', 'start', 'end', 'state'])
        for rec in self.filtered(lambda a: a.state in ('draft', 'published')):
            guard = rec.employee_id
            if guard.company_id != rec.company_id or rec.shift_id.company_id != rec.company_id or not guard.active or not guard.is_security_guard or not guard.security_eligible:
                raise ValidationError(_('Assignments require an active, eligible guard in the same company.'))
            if rec.site_id not in guard.security_site_ids:
                raise ValidationError(_('Authorize this guard for the assignment site first.'))
            if rec.override_reason and not self.env.su and not self.env.user.has_group('dct_security_management.group_manager'):
                raise AccessError(_('Only operations managers can record a working-time override.'))
            # SQL deliberately checks every assignment, including records outside this user's site scope.
            self.env.cr.execute("SELECT id FROM dct_security_assignment WHERE employee_id=%s AND id<>%s AND state IN ('draft','published') AND start<%s AND \"end\">%s LIMIT 1", [guard.id, rec.id, rec.end, rec.start])
            if self.env.cr.fetchone():
                raise ValidationError(_('This guard already has an overlapping assignment.'))
            self.env['hr.leave'].flush_model(['employee_id', 'state', 'date_from', 'date_to'])
            self.env.cr.execute("SELECT id FROM hr_leave WHERE employee_id=%s AND state='validate' AND date_from<%s AND date_to>%s LIMIT 1", [guard.id, rec.end, rec.start])
            if self.env.cr.fetchone():
                raise ValidationError(_('This guard has approved time off during the shift.'))
            qualifications = guard.qualification_ids.filtered(lambda q: not q.expiry_date or q.expiry_date >= rec.shift_id.local_date).mapped('qualification_id')
            if rec.shift_id.qualification_ids - qualifications:
                raise ValidationError(_('The guard lacks a required current qualification.'))
            rest = timedelta(hours=rec.company_id.dct_rest_hours)
            self.env.cr.execute("SELECT id FROM dct_security_assignment WHERE employee_id=%s AND id<>%s AND state IN ('draft','published') AND start<%s AND \"end\">%s LIMIT 1", [guard.id, rec.id, rec.end + rest, rec.start - rest])
            rest_conflict = bool(self.env.cr.fetchone())
            duration = (rec.end - rec.start).total_seconds() / 3600
            if rest_conflict or (rec.company_id.dct_max_shift_hours and duration > rec.company_id.dct_max_shift_hours):
                if not (rec.override_reason or '').strip() or not (self.env.su or self.env.user.has_group('dct_security_management.group_manager')):
                    raise ValidationError(_('Working-time/rest policy conflict: an operations manager must provide an override reason.'))

    @api.constrains('shift_id', 'employee_id', 'company_id', 'override_reason')
    def _check_assignment(self):
        self._validate_assignment()

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'leave_conflict', 'approved_overtime_hours', 'overtime_approved_by', 'overtime_approved_at', 'worked_hours', 'approved_hours', 'proposed_overtime_hours', 'scheduled_hours', 'site_id', 'start', 'end'}
        if any(v.get('state', 'draft') != 'draft' or protected.intersection(v) for v in vals_list):
            raise AccessError(_('Create assignments as drafts.'))
        shifts = self.env['dct.security.shift'].browse(sorted({v['shift_id'] for v in vals_list if v.get('shift_id')}))
        # Serialize additions with publication so a published shift cannot gain an unreviewed draft.
        shifts._lock()
        if any(shift.state != 'draft' for shift in shifts):
            raise UserError(_('Add guards to draft shifts or use the replacement action.'))
        employee_ids = sorted({v['employee_id'] for v in vals_list if v.get('employee_id')})
        if employee_ids:
            # Take the row lock before INSERT acquires employee foreign-key locks.
            self.env.cr.execute('SELECT id FROM hr_employee WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(employee_ids)])
            self.env.cr.execute('UPDATE hr_employee SET write_date=clock_timestamp() WHERE id IN %s', [tuple(employee_ids)])
        records = super().create(vals_list)
        if any(r.shift_id.state != 'draft' for r in records):
            raise UserError(_('Add guards to draft shifts or use the replacement action.'))
        return records

    def write(self, vals):
        if {'state', 'leave_conflict', 'approved_overtime_hours', 'overtime_approved_by', 'overtime_approved_at', 'worked_hours', 'approved_hours', 'proposed_overtime_hours', 'scheduled_hours', 'site_id', 'start', 'end'}.intersection(vals):
            raise AccessError(_('Use the controlled assignment and overtime actions.'))
        if {'shift_id', 'employee_id', 'company_id', 'override_reason'}.intersection(vals) and any(rec.state != 'draft' for rec in self):
            raise UserError(_('Published assignment details are frozen. Use a replacement.'))
        return super().write(vals)

    def _publish(self):
        self._validate_assignment()
        super(Assignment, self).write({'state': 'published'})

    def action_replace(self):
        self.ensure_one()
        self._check_role('group_manager', 'group_supervisor')
        return {'type': 'ir.actions.act_window', 'name': _('Replace Guard'), 'res_model': 'dct.security.replace.guard', 'view_mode': 'form', 'target': 'new', 'context': {'default_assignment_id': self.id}}

    def action_approve_overtime(self):
        self._check_role('group_manager', 'group_hr')
        self._lock()
        for rec in self:
            if any(a.state != 'approved' for a in rec.allocation_ids):
                raise UserError(_('Approve all attendance allocations before overtime.'))
            self.env['dct.security.attendance.period']._check_unlocked(rec.employee_id, rec.start, rec.end)
            rec.allocation_ids._check_consumed()
            super(Assignment, rec).write({'approved_overtime_hours': rec.proposed_overtime_hours, 'overtime_approved_by': self.env.uid, 'overtime_approved_at': fields.Datetime.now()})
        return True

    def action_reconcile_attendance(self):
        self._check_role('group_manager', 'group_supervisor', 'group_hr')
        self._lock()
        for rec in self:
            if rec.state != 'published':
                raise UserError(_('Only published assignments can receive attendance allocations.'))
            for attendance in self.env['hr.attendance'].search([('employee_id', '=', rec.employee_id.id), ('check_in', '<', rec.end), ('check_out', '>', rec.start)]):
                start, end = max(attendance.check_in, rec.start), min(attendance.check_out, rec.end)
                existing = self.env['dct.security.allocation'].search([('assignment_id', '=', rec.id), ('attendance_id', '=', attendance.id), ('start', '=', start), ('end', '=', end)], limit=1)
                if not existing:
                    self.env['dct.security.allocation'].create({'assignment_id': rec.id, 'attendance_id': attendance.id, 'start': start, 'end': end, 'company_id': rec.company_id.id})
        return True

    @api.ondelete(at_uninstall=False)
    def _unlink_draft_only(self):
        if any(rec.state != 'draft' or rec.allocation_ids for rec in self):
            raise UserError(_('Only unused draft assignments can be deleted.'))


class Replacement(models.Model):
    _name = 'dct.security.replacement'
    _description = 'Guard Replacement Audit'
    _inherit = ['dct.security.mixin']
    _order = 'replaced_at desc'

    old_assignment_id = fields.Many2one('dct.security.assignment', required=True, ondelete='restrict')
    new_assignment_id = fields.Many2one('dct.security.assignment', required=True, ondelete='restrict')
    site_id = fields.Many2one(related='old_assignment_id.site_id', store=True)
    reason = fields.Text(required=True)
    replaced_by = fields.Many2one('res.users', required=True, default=lambda self: self.env.user, readonly=True)
    replaced_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('dct_replacement_token') is not _REPLACEMENT_TOKEN:
            raise AccessError(_('Replacement history is recorded only by the replacement workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Replacement history is immutable.'))

    @api.ondelete(at_uninstall=False)
    def _unlink_history(self):
        raise UserError(_('Replacement history cannot be deleted.'))


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._dct_refresh_leave_conflicts(records.employee_id)
        return records

    def _dct_refresh_leave_conflicts(self, employees):
        if not employees:
            return
        self.env.cr.execute('SELECT id FROM hr_employee WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(employees.ids))])
        self.env.cr.execute('UPDATE hr_employee SET write_date=clock_timestamp() WHERE id IN %s', [tuple(employees.ids)])
        self.flush_recordset(['employee_id', 'state', 'date_from', 'date_to'])
        self.env['dct.security.assignment'].flush_model(['employee_id', 'state', 'start', 'end'])
        # Integrity flag only: leave approval keeps the roster and signals manual replacement.
        self.env.cr.execute("""UPDATE dct_security_assignment a SET leave_conflict=EXISTS(
            SELECT 1 FROM hr_leave l WHERE l.employee_id=a.employee_id AND l.state='validate'
            AND l.date_from<a.\"end\" AND l.date_to>a.start)
            WHERE a.employee_id IN %s AND a.state IN ('draft','published') RETURNING a.id""", [tuple(employees.ids)])
        assignments = self.env['dct.security.assignment'].browse([row[0] for row in self.env.cr.fetchall()])
        assignments.invalidate_recordset(['leave_conflict'])
        assignments.modified(['leave_conflict'])

    def write(self, vals):
        employees = self.employee_id
        if 'state' in vals or {'date_from', 'date_to', 'employee_id'}.intersection(vals):
            ids = sorted(set(employees.ids + ([vals['employee_id']] if vals.get('employee_id') else [])))
            if ids:
                self.env.cr.execute('SELECT id FROM hr_employee WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(ids)])
                self.env.cr.execute('UPDATE hr_employee SET write_date=clock_timestamp() WHERE id IN %s', [tuple(ids)])
        result = super().write(vals)
        if {'state', 'date_from', 'date_to', 'employee_id'}.intersection(vals):
            employees |= self.employee_id
            self._dct_refresh_leave_conflicts(employees)
        return result
