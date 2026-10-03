from datetime import timedelta
import pytz

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError, UserError
from odoo.tools import SQL


class SecurityMixin(models.AbstractModel):
    _name = 'dct.security.mixin'
    _description = 'Security operations access and audit helpers'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    lock_version = fields.Integer(default=0, readonly=True, groups='base.group_system', copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._check_link_access()
        return records

    def write(self, vals):
        result = super().write(vals)
        self._check_link_access()
        return result

    def _check_link_access(self):
        for rec in self:
            if not self.env.su and rec.company_id not in self.env.companies:
                raise AccessError(_('Select an allowed company before editing this record.'))
            for field_name in ('site_id', 'site_ids', 'post_id', 'employee_id', 'guard_ids', 'supervisor_id'):
                if field_name in rec._fields:
                    rec[field_name].check_access('read')

    def _check_role(self, *roles):
        if not self.env.su and not any(self.env.user.has_group('dct_security_management.' + role) for role in roles):
            raise AccessError(_('Your security operations role does not permit this action.'))
        self.check_access('write')

    def _lock(self):
        self.check_access('write')
        if self.ids:
            self.flush_recordset()
            self.env.cr.execute(SQL('SELECT id FROM %s WHERE id IN %s ORDER BY id FOR UPDATE',
                                    SQL.identifier(self._table), tuple(sorted(self.ids))))
            # Odoo uses REPEATABLE READ. A lock alone does not refresh a waiting
            # worker's snapshot when only children changed. Touch the common row
            # so the losing transaction raises SerializationFailure and retries.
            self.env.cr.execute(SQL('UPDATE %s SET lock_version = COALESCE(lock_version, 0) + 1 WHERE id IN %s',
                                    SQL.identifier(self._table), tuple(sorted(self.ids))))
            self.invalidate_recordset()

    def _activity_once(self, user, summary, note='', deadline=None):
        """Private helper: internal activities only; caller's record rules still apply."""
        self.ensure_one()
        if not user or not user.active or user.share or not self.with_user(user).has_access('read'):
            return
        self._lock()
        activity_type = self.env.ref('mail.mail_activity_data_todo')
        existing = self.env['mail.activity'].search([
            ('res_model', '=', self._name), ('res_id', '=', self.id),
            ('user_id', '=', user.id), ('summary', '=', summary),
        ], limit=1)
        if not existing:
            self.activity_schedule(activity_type_id=activity_type.id, user_id=user.id,
                                   summary=summary, note=note, date_deadline=deadline or fields.Date.today())

    def message_subscribe(self, partner_ids=None, subtype_ids=None):
        # Followers are not an alternative access path. External contacts must never
        # receive operational or financial information through chatter notifications.
        for partner in self.env['res.partner'].browse(partner_ids or []):
            allowed = partner.user_ids.filtered(lambda u: u.active and not u.share)
            if not any(all(rec.with_user(u).has_access('read') for rec in self) for u in allowed):
                raise AccessError(_('Only internal users who can read this record may follow it.'))
        return super().message_subscribe(partner_ids=partner_ids, subtype_ids=subtype_ids)

    def _notify_get_recipients(self, message, msg_vals=False, **kwargs):
        recipients = super()._notify_get_recipients(message, msg_vals=msg_vals, **kwargs)
        # Re-evaluate on every notification: users can lose site responsibility.
        partner_ids = [r['id'] for r in recipients]
        allowed = set()
        for partner in self.env['res.partner'].browse(partner_ids):
            if any(all(rec.with_user(u).has_access('read') for rec in self)
                   for u in partner.user_ids.filtered(lambda u: u.active and not u.share)):
                allowed.add(partner.id)
        return [r for r in recipients if r['id'] in allowed]

    @api.ondelete(at_uninstall=False)
    def _protect_history(self):
        if 'state' in self._fields and any(r.state not in ('draft', False) for r in self):
            raise UserError(_('Confirmed operational history cannot be deleted. Archive or cancel it instead.'))


class SecurityUsers(models.Model):
    _inherit = 'res.users'

    def _dct_is_user(self):
        self.ensure_one()
        return any(self.has_group('dct_security_management.' + role)
                   for role in ('group_manager', 'group_supervisor', 'group_hr', 'group_finance', 'group_readonly'))

    def _dct_site_limited(self):
        self.ensure_one()
        return self.has_group('dct_security_management.group_supervisor') and not any(
            self.has_group('dct_security_management.' + role) for role in ('group_manager', 'group_hr', 'group_finance'))

    def _dct_employee_domain(self, prefix=''):
        self.ensure_one()
        if not self._dct_is_user():
            return [(1, '=', 1)]
        domain = [(prefix + 'company_id', 'in', self.env.companies.ids), '|',
                  (prefix + 'is_security_guard', '=', True), (prefix + 'is_security_supervisor', '=', True)]
        if self._dct_site_limited():
            domain.append((prefix + 'security_site_ids.supervisor_ids', 'in', [self.id]))
        return domain


class SecurityCompany(models.Model):
    _inherit = 'res.company'

    dct_grace_minutes = fields.Integer('Late grace (minutes)', default=15)
    dct_max_open_hours = fields.Float('Maximum live open attendance (hours)', default=16)
    dct_map_tile_url = fields.Char('Map tile URL', help='Optional HTTPS URL with {z}, {x}, {y}. Browsers contact this provider only when configured.')
    dct_map_attribution = fields.Char('Map attribution')
    dct_automation_enabled = fields.Boolean('Enable security operations automation')
    dct_reminder_days = fields.Integer('Expiry reminder lead days', default=30)

    @api.constrains('dct_grace_minutes', 'dct_max_open_hours', 'dct_reminder_days', 'dct_map_tile_url', 'dct_map_attribution')
    def _check_security_policy(self):
        for rec in self:
            if rec.dct_grace_minutes < 0 or rec.dct_max_open_hours <= 0 or rec.dct_reminder_days < 0:
                raise ValidationError(_('Attendance and reminder limits must be nonnegative, with a positive maximum open duration.'))
            if rec.dct_map_tile_url and (not rec.dct_map_tile_url.startswith('https://') or
                    not all(x in rec.dct_map_tile_url for x in ('{z}', '{x}', '{y}')) or not rec.dct_map_attribution):
                raise ValidationError(_('Configure an HTTPS tile URL containing {z}, {x}, {y} and its required attribution.'))


class SecuritySite(models.Model):
    _name = 'dct.security.site'
    _description = 'Security site'
    _inherit = ['dct.security.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(required=True, tracking=True, index=True)
    active = fields.Boolean(default=True)
    partner_id = fields.Many2one('res.partner', string='Customer', required=True, check_company=True, tracking=True)
    street = fields.Char()
    street2 = fields.Char()
    city = fields.Char()
    country_id = fields.Many2one('res.country')
    latitude = fields.Float(digits=(10, 7))
    longitude = fields.Float(digits=(10, 7))
    has_coordinates = fields.Boolean('Coordinates configured', help='Enable to distinguish a real coordinate at zero from an unconfigured site.')
    tz = fields.Selection([(tz, tz) for tz in pytz.all_timezones], required=True, default='Asia/Baghdad')
    supervisor_ids = fields.Many2many('res.users', string='Responsible supervisors', domain=[('share', '=', False)])
    state = fields.Selection([('active', 'Operating'), ('inactive', 'Inactive')], default='active', required=True, tracking=True)
    instructions = fields.Html(sanitize=True)
    contact_ids = fields.Many2many('res.partner', string='Site contacts', check_company=True)
    image_1920 = fields.Image('Site photo')
    post_ids = fields.One2many('dct.security.post', 'site_id', string='Posts')
    guard_ids = fields.Many2many('hr.employee', 'dct_employee_site_rel', 'site_id', 'employee_id', string='Eligible site guards', check_company=True)
    required_count = fields.Integer(compute='_compute_coverage', string='Required now')
    assigned_count = fields.Integer(compute='_compute_coverage', string='Assigned now')
    present_count = fields.Integer(compute='_compute_coverage', string='Present now')
    missing_count = fields.Integer(compute='_compute_coverage', string='Missing now')

    @api.constrains('latitude', 'longitude', 'supervisor_ids', 'company_id', 'guard_ids')
    def _check_site(self):
        for site in self:
            if not -90 <= site.latitude <= 90 or not -180 <= site.longitude <= 180:
                raise ValidationError(_('Coordinates are outside the valid latitude/longitude range.'))
            if any(site.company_id not in user.company_ids or user.share for user in site.supervisor_ids):
                raise ValidationError(_('Supervisors must be internal users allowed in the site company.'))
            if any(not emp.is_security_guard or emp.company_id != site.company_id for emp in site.guard_ids):
                raise ValidationError(_('Site guards must be security guards in the site company.'))

    def _compute_coverage(self):
        values = {rec.id: [0, 0, 0] for rec in self}
        if 'dct.security.shift' in self.env.registry:
            now = fields.Datetime.now()
            shifts = self.env['dct.security.shift'].search([
                ('site_id', 'in', self.ids), ('state', '=', 'published'), ('start', '<=', now), ('end', '>', now)])
            shifts.assignment_ids.employee_id._compute_security_status()
            for shift in shifts:
                row = values[shift.site_id.id]
                assignments = shift.assignment_ids.filtered(lambda a: a.state == 'published')
                row[0] += shift.required_guards
                row[1] += len(assignments)
                row[2] += sum(a.employee_id.security_status == 'on_duty' for a in assignments)
        for rec in self:
            rec.required_count, rec.assigned_count, rec.present_count = values[rec.id]
            rec.missing_count = max(0, rec.required_count - rec.present_count)

    def action_shifts(self):
        self.ensure_one()
        return self._related_action('dct.security.shift', 'Security shifts')

    def action_contracts(self):
        self.ensure_one()
        return self._related_action('dct.security.contract', 'Contracts', 'site_ids')

    def action_incidents(self):
        return self._related_action('dct.security.incident', 'Incidents')

    def action_patrols(self):
        return self._related_action('dct.security.patrol.round', 'Patrols')

    def action_visits(self):
        return self._related_action('dct.security.visit', 'Supervisor visits')

    def _related_action(self, model, name, field='site_id'):
        self.ensure_one()
        self.check_access('read')
        return {'type': 'ir.actions.act_window', 'name': _(name), 'res_model': model,
                'views': [(False, 'list'), (False, 'form')], 'domain': [(field, 'in', self.ids)],
                'context': {'default_site_id': self.id, 'default_company_id': self.company_id.id}}


class SecurityPost(models.Model):
    _name = 'dct.security.post'
    _description = 'Security post'
    _inherit = 'dct.security.mixin'
    _order = 'site_id, name'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    site_id = fields.Many2one('dct.security.site', required=True, ondelete='restrict', check_company=True, index=True)
    instructions = fields.Text()
    _name_site_unique = models.Constraint('UNIQUE(site_id,name)', 'A post name must be unique within its site.')


class SecurityQualification(models.Model):
    _name = 'dct.security.qualification'
    _description = 'Guard qualification type'
    _inherit = 'dct.security.mixin'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)


class GuardQualification(models.Model):
    _name = 'dct.security.guard.qualification'
    _description = 'Guard qualification and expiry'
    _inherit = ['dct.security.mixin', 'mail.thread', 'mail.activity.mixin']
    _rec_name = 'qualification_id'

    employee_id = fields.Many2one('hr.employee', required=True, ondelete='restrict', check_company=True, index=True)
    qualification_id = fields.Many2one('dct.security.qualification', required=True, ondelete='restrict', check_company=True)
    expiry_date = fields.Date(required=True, index=True, tracking=True)
    certificate = fields.Binary(groups='dct_security_management.group_hr', attachment=True)
    certificate_name = fields.Char(groups='dct_security_management.group_hr')
    _guard_qualification_unique = models.Constraint('UNIQUE(employee_id, qualification_id)', 'Each qualification may appear once per guard; update its renewal date.')


class SecurityEmployee(models.Model):
    _inherit = 'hr.employee'

    is_security_guard = fields.Boolean('Is Security Guard', index=True)
    is_security_supervisor = fields.Boolean('Is Security Supervisor', index=True)
    guard_code = fields.Char('Guard code', copy=False, index=True)
    security_rank = fields.Char('Rank / operational role')
    security_supervisor_id = fields.Many2one('hr.employee', string='Operational supervisor', check_company=True)
    security_eligible = fields.Boolean('Operationally eligible', default=True)
    security_site_ids = fields.Many2many('dct.security.site', 'dct_employee_site_rel', 'employee_id', 'site_id', string='Authorized sites', check_company=True)
    qualification_ids = fields.One2many('dct.security.guard.qualification', 'employee_id', string='Qualifications')
    security_status = fields.Selection([
        ('on_duty', 'On Duty'), ('off_duty', 'Off Duty'), ('on_leave', 'On Leave'),
        ('late', 'Late / Not Checked In'), ('missing_checkout', 'Missing Checkout'),
    ], compute='_compute_security_status', string='Operational status')
    _guard_code_unique = models.Constraint('UNIQUE(company_id,guard_code)', 'Guard code must be unique within the company.')

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.su or self.env.user.has_group('hr.group_hr_user'):
            return super().create(vals_list)
        self.check_access('create')
        if not any(self.env.user.has_group('dct_security_management.' + role) for role in ('group_manager', 'group_hr')):
            return super().create(vals_list)
        allowed = {'name','company_id','is_security_guard','is_security_supervisor','guard_code',
                   'security_rank','security_supervisor_id','security_eligible','security_site_ids',
                   'work_phone','work_email','mobile_phone','image_1920','active'}
        for vals in vals_list:
            if set(vals) - allowed or not (vals.get('is_security_guard') or vals.get('is_security_supervisor')):
                raise AccessError(_('Operations staff can create guards and operational supervisors with operational fields only. Save the employee before adding qualifications.'))
            if vals.get('company_id', self.env.company.id) not in self.env.companies.ids:
                raise AccessError(_('The employee company must be allowed for your user.'))
            site_ids = []
            for command in vals.get('security_site_ids', []):
                if command[0] not in (3, 4, 5, 6):
                    raise AccessError(_('Select existing authorized sites when creating an employee.'))
                site_ids.extend(command[2] if command[0] == 6 else [command[1]] if command[0] in (3, 4) else [])
            self.env['dct.security.site'].browse(site_ids).check_access('read')
            self.browse(vals.get('security_supervisor_id', [])).check_access('read')
        # Odoo 19 delegates employee creation to a mandatory hr.version record.
        # This narrowly scoped bootstrap allows only the checked operational
        # fields above; it grants no HR group or hr.version ACL and returns to
        # the caller's environment immediately. Caller defaults cannot inject
        # private salary/version data into the elevated creation.
        context = {key: self.env.context[key] for key in ('lang', 'tz', 'allowed_company_ids') if key in self.env.context}
        records = super(SecurityEmployee, self.sudo().with_context(context)).create(vals_list).with_env(self.env)
        records.check_access('read')
        return records

    @api.constrains('guard_code', 'is_security_guard', 'security_site_ids')
    def _check_guard(self):
        for rec in self:
            if rec.is_security_guard and not (rec.guard_code or '').strip():
                raise ValidationError(_('Security guards require a company-unique guard code.'))
            if any(site.company_id != rec.company_id for site in rec.security_site_ids):
                raise ValidationError(_('Authorized sites must belong to the guard company.'))

    def _compute_security_status(self):
        now = fields.Datetime.now()
        current = {}
        attendance = {}
        leave_ids = set()
        if 'dct.security.assignment' in self.env.registry:
            assignments = self.env['dct.security.assignment'].search([
                ('employee_id', 'in', self.ids), ('state', '=', 'published'), ('start', '<=', now), ('end', '>', now)])
            current = {a.employee_id.id: a for a in assignments}
            attendances = self.env['hr.attendance'].search([
                ('employee_id', 'in', self.ids), ('check_in', '<=', now),
                '|', ('check_out', '=', False), ('check_out', '>', now)], order='check_in desc')
            attendance = {a.employee_id.id: a for a in attendances}
        leave_ids = self._security_current_leave_ids(now)
        for rec in self:
            shift, event = current.get(rec.id), attendance.get(rec.id)
            status = 'off_duty'
            if rec.id in leave_ids or (shift and getattr(shift, 'leave_conflict', False)):
                status = 'on_leave'
            elif event and not event.check_out and now - event.check_in > timedelta(hours=rec.company_id.dct_max_open_hours):
                status = 'missing_checkout'
            elif shift and event and event.check_in < shift.end:
                status = 'on_duty'
            elif shift and now > shift.start + timedelta(minutes=rec.company_id.dct_grace_minutes):
                status = 'late'
            rec.security_status = status

    def _security_current_leave_ids(self, now=None):
        """Only approved-leave presence for authorized employees, never details."""
        self.check_access('read')
        if not self:
            return set()
        now = now or fields.Datetime.now()
        self.env['hr.leave'].flush_model(['employee_id','state','date_from','date_to'])
        self.env.cr.execute('''SELECT DISTINCT employee_id FROM hr_leave
            WHERE employee_id IN %s AND state='validate' AND date_from <= %s AND date_to > %s''',
            [tuple(self.ids), now, now])
        return {row[0] for row in self.env.cr.fetchall()}

    def _security_action(self, model, name, field='employee_id'):
        self.ensure_one()
        self.check_access('read')
        return {'type': 'ir.actions.act_window', 'name': _(name), 'res_model': model,
                'views': [(False, 'list'), (False, 'form')], 'domain': [(field, 'in', self.ids)],
                'context': {'default_employee_id': self.id, 'default_company_id': self.company_id.id}}

    def action_security_assignments(self):
        return self._security_action('dct.security.assignment', 'Assignments')

    def action_security_attendance(self):
        return self._security_action('hr.attendance', 'Attendance')

    def action_security_incidents(self):
        return self._security_action('dct.security.incident', 'Incidents', 'guard_ids')

    def action_security_patrols(self):
        return self._security_action('dct.security.patrol.round', 'Patrols')

    def action_security_payroll(self):
        if not self.env.user.has_group('dct_security_management.group_finance'):
            raise AccessError(_('Finance authorization is required.'))
        return self._security_action('dct.security.payroll', 'Payroll worksheets')


class SecurityEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'

    is_security_guard = fields.Boolean(readonly=True)
    is_security_supervisor = fields.Boolean(readonly=True)
    guard_code = fields.Char(readonly=True)
    security_site_ids = fields.Many2many('dct.security.site', 'dct_employee_site_rel', 'employee_id', 'site_id', readonly=True)
